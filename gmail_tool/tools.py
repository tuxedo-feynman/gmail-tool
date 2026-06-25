import base64
import email.utils
import json
import logging
import time
from collections import defaultdict

from .config import Config
from .models import (
    Attachment,
    Email,
    EmailListItem,
    MailboxStats,
    RecipientGroup,
    SenderGroup,
)

logger = logging.getLogger(__name__)


class GmailTools:
    def __init__(self, gmail_service, drive_service, config: Config, user_email: str):
        self._gmail = gmail_service
        self._drive = drive_service
        self._config = config
        self._user_email = user_email
        self._label_cache: dict[str, str] = {}

    # -------------------------------------------------------------------------
    # Public tools
    # -------------------------------------------------------------------------

    def initialize(self, reset: bool = False) -> dict:
        state_path = self._config.state_path
        q = self._excluded_labels_query()

        # Resume from checkpoint unless reset is requested
        all_ids: list[str] = []
        page_token: str | None = None
        if not reset and state_path.exists():
            existing = json.loads(state_path.read_text())
            if existing.get("status") == "in_progress":
                all_ids = existing.get("message_ids", [])
                page_token = existing.get("next_page_token")
                logger.info(
                    "Resuming from checkpoint: %d IDs collected so far", len(all_ids)
                )

        state_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            kwargs: dict = {"userId": "me", "maxResults": 500}
            if q:
                kwargs["q"] = q
            if page_token:
                kwargs["pageToken"] = page_token

            result = _retry(
                lambda: self._gmail.users().messages().list(**kwargs).execute()
            )
            all_ids.extend(m["id"] for m in result.get("messages", []))
            page_token = result.get("nextPageToken")
            logger.debug("Collected %d message IDs so far", len(all_ids))

            # Checkpoint after every page so a crash can resume
            state_path.write_text(json.dumps({
                "status": "in_progress",
                "next_page_token": page_token,
                "message_ids": all_ids,
            }))

            if not page_token:
                break

        all_ids.reverse()
        state_path.write_text(json.dumps({"status": "complete", "message_ids": all_ids}))

        logger.info("Initialized state with %d emails (oldest-first)", len(all_ids))
        return {"total_emails": len(all_ids), "state_file": str(state_path)}

    def get_mailbox_stats(self) -> MailboxStats:
        profile = self._gmail.users().getProfile(userId="me").execute()
        total_count = profile.get("messagesTotal", 0)

        about = self._drive.about().get(fields="storageQuota").execute()
        quota = about.get("storageQuota", {})
        quota_bytes = int(quota.get("limit", 0))
        used_bytes = int(quota.get("usage", 0))

        excluded_count = 0
        for label in self._config.excluded_labels:
            try:
                result = self._gmail.users().messages().list(
                    userId="me", q=f"label:{label}", maxResults=1
                ).execute()
                excluded_count += result.get("resultSizeEstimate", 0)
            except Exception as e:
                logger.warning("Could not count emails for label %s: %s", label, e)

        return MailboxStats(
            quota_bytes=quota_bytes,
            used_bytes=used_bytes,
            total_email_count=total_count,
            excluded_email_count=excluded_count,
            actionable_email_count=max(0, total_count - excluded_count),
        )

    def list_emails_by_age(self, cursor: int) -> dict:
        state = self._load_state()
        all_ids = state["message_ids"]

        batch = all_ids[cursor: cursor + self._config.scan_page_size]
        next_cursor = cursor + len(batch) if cursor + len(batch) < len(all_ids) else None

        emails = []
        for msg_id in batch:
            msg = self._gmail.users().messages().get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["From", "To", "Cc", "Subject", "Date"],
            ).execute()
            emails.append(self._parse_email_list_item(msg))

        return {"emails": emails, "next_cursor": next_cursor}

    def list_emails_by_sender(self, page_token: str | None) -> dict:
        message_ids, next_page_token = self._list_message_ids(
            page_token, self._config.sender_page_size
        )
        groups: dict[str, dict] = {}

        for msg_id in message_ids:
            msg = self._gmail.users().messages().get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["From", "Date"],
            ).execute()

            headers = msg.get("payload", {}).get("headers", [])
            from_header = _get_header(headers, "From")
            display_name, address = email.utils.parseaddr(from_header)
            if not address:
                continue

            date = _get_header(headers, "Date")
            size = msg.get("sizeEstimate", 0)

            if address not in groups:
                groups[address] = {
                    "address": address,
                    "display_name": display_name or None,
                    "email_count": 0,
                    "total_gmail_size_bytes": 0,
                    "oldest_sent_at": date,
                    "newest_sent_at": date,
                    "email_ids": [],
                }

            g = groups[address]
            g["email_count"] += 1
            g["total_gmail_size_bytes"] += size
            g["email_ids"].append(msg_id)
            g["newest_sent_at"] = date

        senders = sorted(
            [SenderGroup(**g) for g in groups.values()],
            key=lambda s: s.email_count,
            reverse=True,
        )
        return {"senders": senders, "next_page_token": next_page_token}

    def list_emails_by_recipient(self, page_token: str | None) -> dict:
        message_ids, next_page_token = self._list_message_ids(
            page_token, self._config.sender_page_size
        )
        groups: dict[str, dict] = {}

        for msg_id in message_ids:
            msg = self._gmail.users().messages().get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["To", "Cc", "Date"],
            ).execute()

            headers = msg.get("payload", {}).get("headers", [])
            date = _get_header(headers, "Date")
            size = msg.get("sizeEstimate", 0)

            all_recipients = _parse_addresses(
                _get_header(headers, "To")
            ) + _parse_addresses(_get_header(headers, "Cc"))

            # Group by recipients that are not the user (i.e. list addresses)
            list_addresses = [a for a in all_recipients if a != self._user_email]
            if not list_addresses:
                list_addresses = all_recipients

            for address in list_addresses:
                display_name = ""
                if address not in groups:
                    groups[address] = {
                        "address": address,
                        "display_name": None,
                        "email_count": 0,
                        "total_gmail_size_bytes": 0,
                        "oldest_sent_at": date,
                        "newest_sent_at": date,
                        "email_ids": [],
                    }

                g = groups[address]
                g["email_count"] += 1
                g["total_gmail_size_bytes"] += size
                if msg_id not in g["email_ids"]:
                    g["email_ids"].append(msg_id)
                g["newest_sent_at"] = date

        recipients = sorted(
            [RecipientGroup(**g) for g in groups.values()],
            key=lambda r: r.email_count,
            reverse=True,
        )
        return {"recipients": recipients, "next_page_token": next_page_token}

    def get_emails(self, email_ids: list[str]) -> dict:
        emails = []
        failed_ids = []

        for msg_id in email_ids:
            try:
                msg = self._gmail.users().messages().get(
                    userId="me", id=msg_id, format="full"
                ).execute()
                emails.append(self._parse_email(msg))
            except Exception as e:
                logger.warning("Failed to fetch email %s: %s", msg_id, e)
                failed_ids.append(msg_id)

        return {"emails": emails, "failed_ids": failed_ids}

    def trash_emails(self, email_ids: list[str]) -> dict:
        trashed_count = 0
        failed_ids = []

        for msg_id in email_ids:
            try:
                self._gmail.users().messages().trash(
                    userId="me", id=msg_id
                ).execute()
                trashed_count += 1
                logger.debug("Trashed email %s", msg_id)
            except Exception as e:
                logger.warning("Failed to trash email %s: %s", msg_id, e)
                failed_ids.append(msg_id)

        logger.info("Trashed %d emails, %d failures", trashed_count, len(failed_ids))
        return {"trashed_count": trashed_count, "failed_ids": failed_ids}

    def label_emails(self, email_ids: list[str], label: str) -> dict:
        label_id = self._get_or_create_label(label)
        labeled_count = 0
        failed_ids = []

        for msg_id in email_ids:
            try:
                self._gmail.users().messages().modify(
                    userId="me",
                    id=msg_id,
                    body={"addLabelIds": [label_id]},
                ).execute()
                labeled_count += 1
                logger.debug("Applied label '%s' to email %s", label, msg_id)
            except Exception as e:
                logger.warning(
                    "Failed to label email %s with '%s': %s", msg_id, label, e
                )
                failed_ids.append(msg_id)

        logger.info(
            "Labeled %d emails with '%s', %d failures",
            labeled_count,
            label,
            len(failed_ids),
        )
        return {"labeled_count": labeled_count, "failed_ids": failed_ids}

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _load_state(self) -> dict:
        state_path = self._config.state_path
        if not state_path.exists():
            raise RuntimeError(
                f"State file not found at {state_path}. Run initialize() first."
            )
        state = json.loads(state_path.read_text())
        if state.get("status") == "in_progress":
            raise RuntimeError(
                "Initialization was interrupted. Run initialize() to resume."
            )
        return state

    def _excluded_labels_query(self) -> str:
        return " ".join(
            f"-label:{label}" for label in self._config.excluded_labels
        )

    def _list_message_ids(
        self, page_token: str | None, page_size: int
    ) -> tuple[list[str], str | None]:
        kwargs: dict = {"userId": "me", "maxResults": page_size}
        q = self._excluded_labels_query()
        if q:
            kwargs["q"] = q
        if page_token:
            kwargs["pageToken"] = page_token

        result = self._gmail.users().messages().list(**kwargs).execute()
        ids = [m["id"] for m in result.get("messages", [])]
        return ids, result.get("nextPageToken")

    def _get_or_create_label(self, label_name: str) -> str:
        if label_name in self._label_cache:
            return self._label_cache[label_name]

        result = self._gmail.users().labels().list(userId="me").execute()
        for label in result.get("labels", []):
            if label["name"] == label_name:
                self._label_cache[label_name] = label["id"]
                return label["id"]

        created = self._gmail.users().labels().create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        ).execute()

        label_id = created["id"]
        self._label_cache[label_name] = label_id
        logger.info("Created Gmail label: %s", label_name)
        return label_id

    def _parse_email_list_item(self, msg: dict) -> EmailListItem:
        headers = msg.get("payload", {}).get("headers", [])
        return EmailListItem(
            message_id=msg["id"],
            thread_id=msg["threadId"],
            sent_at=_get_header(headers, "Date"),
            from_address=email.utils.parseaddr(_get_header(headers, "From"))[1],
            to=_parse_addresses(_get_header(headers, "To")),
            cc=_parse_addresses(_get_header(headers, "Cc")),
            subject=_get_header(headers, "Subject"),
            labels=msg.get("labelIds", []),
            gmail_size_bytes=msg.get("sizeEstimate", 0),
        )

    def _parse_email(self, msg: dict) -> Email:
        headers = msg.get("payload", {}).get("headers", [])
        to = _parse_addresses(_get_header(headers, "To"))
        cc = _parse_addresses(_get_header(headers, "Cc"))
        bcc = self._user_email not in to and self._user_email not in cc

        return Email(
            message_id=msg["id"],
            thread_id=msg["threadId"],
            sent_at=_get_header(headers, "Date"),
            from_address=email.utils.parseaddr(_get_header(headers, "From"))[1],
            to=to,
            cc=cc,
            bcc=bcc,
            subject=_get_header(headers, "Subject"),
            body=_extract_body(msg.get("payload", {})),
            labels=msg.get("labelIds", []),
            gmail_size_bytes=msg.get("sizeEstimate", 0),
            attachments=_extract_attachments(msg.get("payload", {})),
        )


# -------------------------------------------------------------------------
# Module-level helpers (pure functions, easier to test)
# -------------------------------------------------------------------------


def _retry(fn, max_attempts: int = 5, base_delay: float = 2.0):
    for attempt in range(max_attempts):
        try:
            return fn()
        except OSError as e:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Network error (attempt %d/%d): %s — retrying in %.0fs",
                attempt + 1, max_attempts, e, delay,
            )
            time.sleep(delay)
        except Exception as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            if status in (429, 500, 503):
                if attempt == max_attempts - 1:
                    raise
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "API error %d (attempt %d/%d) — retrying in %.0fs",
                    status, attempt + 1, max_attempts, delay,
                )
                time.sleep(delay)
            else:
                raise


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _parse_addresses(header_value: str) -> list[str]:
    if not header_value:
        return []
    addresses = []
    for part in header_value.split(","):
        _, addr = email.utils.parseaddr(part.strip())
        if addr:
            addresses.append(addr)
    return addresses


def _extract_body(payload: dict) -> str:
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        body = _extract_body(part)
        if body:
            return body

    return ""


def _extract_attachments(payload: dict) -> list[Attachment]:
    attachments = []
    for part in payload.get("parts", []):
        filename = part.get("filename", "")
        size = part.get("body", {}).get("size", 0)
        if filename and size > 0:
            attachments.append(
                Attachment(
                    filename=filename,
                    mime_type=part.get("mimeType", ""),
                    gmail_size_bytes=size,
                )
            )
        attachments.extend(_extract_attachments(part))
    return attachments
