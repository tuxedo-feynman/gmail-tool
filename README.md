# gmail-tool

A Gmail cleanup tool designed to be used inside an agent harness. The agent calls these tools to systematically free up space, protect important emails, and surface interesting buried messages.

## Goals

1. **Free up space** — systematically trash old, low-value emails
2. **Protect important mail** — move keepers to a long-term label before bulk cleanup
3. **Surface interesting mail** — flag notable forgotten emails for the user

## How it works

The tool exposes nine operations against the Gmail API. An agent orchestrates calls across three phases:

1. **Quick wins** — `list_emails_by_sender` and `list_emails_by_recipient` reveal high-volume senders and mailing lists. The agent bulk-trashes obvious junk (old newsletters, social notifications, alumni lists) without reviewing individual emails.
2. **Systematic sweep** — `list_emails_by_age` pages through all remaining mail (excluding protected labels). The agent reviews batches via `get_emails` and either trashes or labels each email.
3. **Discovery** — during the sweep, the agent applies an `Interesting` label to buried emails worth surfacing.

Emails labeled with any `excluded_labels` (e.g. `Long-Term`, `Legal`) are skipped entirely and never trashed.

## Setup

### 1. Google Cloud credentials

1. [Create a Google Cloud project](https://console.cloud.google.com/projectcreate)
2. [Enable the Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com) and [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com) for your project
3. [Create an OAuth 2.0 Client ID](https://console.cloud.google.com/apis/credentials/oauthclient) — choose **Desktop app** as the application type
4. Download the credentials JSON and save it (default: `~/.gmail-tool/credentials.json`)

Google's [Python quickstart for the Gmail API](https://developers.google.com/gmail/api/quickstart/python) walks through steps 1–3 in detail if you haven't done this before.

The Drive API is needed solely to read your storage quota. It only requests read-only metadata access — no Drive files are touched.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml` to set your excluded labels and file paths:

```yaml
excluded_labels:
  - Long-Term     # emails you've decided to keep
  - Legal         # anything legally sensitive

scan_page_size: 100      # emails per page in list_emails_by_age
sender_page_size: 50     # emails per page in list_emails_by_sender/recipient

credentials_file: ~/.gmail-tool/credentials.json
oauth_token_file: ~/.gmail-tool/token.json
state_file: ~/.gmail-tool/state.json
```

### 4. First run (OAuth)

The first time you call any tool, a browser window opens to Google's OAuth consent screen. You'll see two permission requests:

- **Gmail** — read, trash, and label emails
- **Google Drive (read-only metadata)** — needed to read your storage quota; no Drive files are accessed

After you approve, an access token and refresh token are saved to `oauth_token_file`. Access tokens expire after an hour; the library refreshes them automatically using the refresh token with no browser prompt. Authentication is silent on every subsequent run unless you revoke access in your Google account settings.

## Usage in an agent harness

```python
from gmail_tool import create_tools

tools = create_tools("config.yaml")

# One-time setup: collect all message IDs oldest-first into state file
tools.initialize()

# Check how much space is used
stats = tools.get_mailbox_stats()

# Page through emails oldest-first using a cursor
cursor = 0
while cursor is not None:
    page = tools.list_emails_by_age(cursor=cursor)
    # agent reviews page["emails"] and decides which to trash/keep
    tools.trash_emails(["id1", "id2"])
    tools.label_emails(["id3"], "Long-Term")
    cursor = page["next_cursor"]
```

## Command-line usage

For one-off experimenting, all read and inspection tools are available directly from the terminal. Output is JSON.

```bash
# First-time setup: collect all message IDs into state file
python -m gmail_tool initialize

# Check storage and email counts
python -m gmail_tool stats

# List the oldest batch of emails (cursor=0 = start)
python -m gmail_tool list-age
python -m gmail_tool list-age --cursor 100

# List emails grouped by sender (most prolific first)
python -m gmail_tool list-senders
python -m gmail_tool list-senders --page-token <token>

# List emails grouped by recipient/mailing list
python -m gmail_tool list-recipients

# Fetch full content for one or more emails (body, attachments, etc.)
python -m gmail_tool get-emails <message_id> [<message_id> ...]

# Download an attachment to a file
python -m gmail_tool get-attachment --message-id <id> --attachment-id <id> --output ./file.pdf
```

The `attachment_id` for a given email is found in the `attachments` array of `get-emails` output.

`initialize` also accepts `--reset` to discard any existing checkpoint and start over:

```bash
python -m gmail_tool initialize --reset
```

Use a non-default config file with `--config`:

```bash
python -m gmail_tool --config ~/my-config.yaml stats
```

Pipe through `jq` to filter output:

```bash
python -m gmail_tool list-senders | jq '.senders[] | {address, email_count}'
```

---

## Tool reference

### `initialize() → dict`

Traverses all mail (excluding `excluded_labels`), collects message IDs oldest-first, and writes them to `state_file`. Must be called once before `list_emails_by_age`. Re-run it to reset the sweep (e.g. after a new batch of cleanup).

```python
{"total_emails": int, "state_file": str}
```

---

### `get_mailbox_stats(unit="bytes") → dict`

Returns current storage quota and email counts. Always fetches live from Gmail. `unit` accepts `"bytes"`, `"mb"`, or `"gb"`.

```python
{
    "unit": str,
    "quota": int | float,
    "used": int | float,
    "total_email_count": int,
    "excluded_email_count": int,
    "actionable_email_count": int
}
```

---

### `list_emails_by_age(cursor) → dict`

Returns a batch of emails from the state file starting at `cursor` (oldest-first). Use `cursor=0` for the first page. Raises `RuntimeError` if `initialize()` has not been run.

```python
{
    "emails": [EmailListItem, ...],
    "next_cursor": int | None   # None when all emails have been covered
}
```

`EmailListItem` fields: `message_id`, `thread_id`, `sent_at`, `from_address`, `to`, `cc`, `subject`, `labels`, `gmail_size_bytes`

---

### `list_emails_by_sender(page_token) → dict`

Pages through emails and groups by sender. Returns groups sorted by `email_count` descending. Useful for bulk-trashing prolific senders.

```python
{
    "senders": [SenderGroup, ...],
    "next_page_token": str | None
}
```

`SenderGroup` fields: `address`, `display_name`, `email_count`, `total_gmail_size_bytes`, `oldest_sent_at`, `newest_sent_at`, `email_ids`

Note: `email_ids` contains only the IDs from this page's scan batch, not every email from that sender globally.

---

### `list_emails_by_recipient(page_token) → dict`

Pages through emails and groups by recipient address. Useful for identifying mailing lists (the list address appears as a non-personal recipient).

```python
{
    "recipients": [RecipientGroup, ...],
    "next_page_token": str | None
}
```

`RecipientGroup` fields: same shape as `SenderGroup`.

---

### `get_emails(email_ids) → dict`

Fetches full content for a list of message IDs.

```python
{
    "emails": [Email, ...],
    "failed_ids": [str, ...]
}
```

`Email` fields: `message_id`, `thread_id`, `sent_at`, `from_address`, `to`, `cc`, `bcc`, `subject`, `body` (plain text; falls back to HTML-stripped if no plain text part), `labels`, `gmail_size_bytes`, `attachments`

`Attachment` fields: `filename`, `mime_type`, `gmail_size_bytes`, `attachment_id`

---

### `get_attachment(message_id, attachment_id) → dict`

Fetches the raw content of an attachment. The `attachment_id` comes from the `attachments` list returned by `get_emails`.

```python
{
    "data": str,       # base64url-encoded bytes
    "size_bytes": int
}
```

---

### `trash_emails(email_ids) → dict`

Moves emails to Gmail trash (recoverable for 30 days).

```python
{"trashed_count": int, "failed_ids": [str, ...]}
```

---

### `label_emails(email_ids, label) → dict`

Applies a label to emails. Creates the label in Gmail if it does not exist.

```python
{"labeled_count": int, "failed_ids": [str, ...]}
```

## Running tests

```bash
pytest tests/
```
