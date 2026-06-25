import base64
import pytest
from unittest.mock import MagicMock, call

from gmail_tool.tools import _get_header, _parse_addresses, _extract_body, _extract_attachments
from tests.conftest import make_raw_message


# -------------------------------------------------------------------------
# Pure helper functions
# -------------------------------------------------------------------------

def test_get_header_found():
    headers = [{"name": "Subject", "value": "Hello"}, {"name": "From", "value": "a@b.com"}]
    assert _get_header(headers, "Subject") == "Hello"


def test_get_header_case_insensitive():
    headers = [{"name": "SUBJECT", "value": "Hello"}]
    assert _get_header(headers, "subject") == "Hello"


def test_get_header_missing():
    assert _get_header([], "Subject") == ""


def test_parse_addresses_single():
    assert _parse_addresses("Alice <alice@example.com>") == ["alice@example.com"]


def test_parse_addresses_multiple():
    result = _parse_addresses("alice@example.com, Bob <bob@example.com>")
    assert result == ["alice@example.com", "bob@example.com"]


def test_parse_addresses_empty():
    assert _parse_addresses("") == []


def test_extract_body_plain_text():
    data = base64.urlsafe_b64encode(b"Hello world").decode()
    payload = {"mimeType": "text/plain", "body": {"data": data}}
    assert _extract_body(payload) == "Hello world"


def test_extract_body_multipart_prefers_plain():
    data = base64.urlsafe_b64encode(b"Plain text").decode()
    payload = {
        "mimeType": "multipart/alternative",
        "body": {},
        "parts": [
            {"mimeType": "text/plain", "body": {"data": data}},
            {"mimeType": "text/html", "body": {"data": ""}},
        ],
    }
    assert _extract_body(payload) == "Plain text"


def test_extract_body_empty():
    assert _extract_body({"mimeType": "text/plain", "body": {}}) == ""


def test_extract_attachments_finds_attachment():
    parts = [
        {
            "filename": "report.pdf",
            "mimeType": "application/pdf",
            "body": {"size": 50000},
            "parts": [],
        }
    ]
    attachments = _extract_attachments({"parts": parts})
    assert len(attachments) == 1
    assert attachments[0].filename == "report.pdf"
    assert attachments[0].gmail_size_bytes == 50000


def test_extract_attachments_ignores_zero_size():
    parts = [{"filename": "empty.txt", "mimeType": "text/plain", "body": {"size": 0}, "parts": []}]
    assert _extract_attachments({"parts": parts}) == []


def test_extract_attachments_nested():
    nested = {
        "parts": [
            {
                "mimeType": "multipart/mixed",
                "body": {},
                "parts": [
                    {
                        "filename": "nested.pdf",
                        "mimeType": "application/pdf",
                        "body": {"size": 1000},
                        "parts": [],
                    }
                ],
            }
        ]
    }
    attachments = _extract_attachments(nested)
    assert len(attachments) == 1
    assert attachments[0].filename == "nested.pdf"


# -------------------------------------------------------------------------
# GmailTools: excluded labels query
# -------------------------------------------------------------------------

# -------------------------------------------------------------------------
# GmailTools: initialize
# -------------------------------------------------------------------------

def test_initialize_collects_and_reverses_ids(tools, mock_gmail, tmp_path, config):
    from gmail_tool.tools import GmailTools
    config.state_file = str(tmp_path / "state.json")
    t = GmailTools(mock_gmail, MagicMock(), config, "me@gmail.com")

    mock_gmail.users.return_value.messages.return_value.list.return_value.execute.side_effect = [
        {"messages": [{"id": "new1"}, {"id": "new2"}], "nextPageToken": "tok"},
        {"messages": [{"id": "old1"}, {"id": "old2"}]},
    ]

    result = t.initialize()

    assert result["total_emails"] == 4
    import json
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["message_ids"] == ["old2", "old1", "new2", "new1"]


def test_initialize_respects_excluded_labels(tools, mock_gmail, tmp_path, config):
    from gmail_tool.tools import GmailTools
    config.state_file = str(tmp_path / "state.json")
    config.excluded_labels = ["Long-Term"]
    t = GmailTools(mock_gmail, MagicMock(), config, "me@gmail.com")

    mock_gmail.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "id1"}]
    }

    t.initialize()

    call_kwargs = mock_gmail.users.return_value.messages.return_value.list.call_args
    assert "-label:Long-Term" in call_kwargs.kwargs.get("q", "")


# -------------------------------------------------------------------------
# GmailTools: list_emails_by_age (cursor-based)
# -------------------------------------------------------------------------

def test_list_emails_by_age_first_page(tools, mock_gmail, tmp_path, config):
    import json
    from gmail_tool.tools import GmailTools
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"message_ids": [f"id{i}" for i in range(25)]}))
    config.state_file = str(state_file)
    config.scan_page_size = 10
    t = GmailTools(mock_gmail, MagicMock(), config, "me@gmail.com")

    mock_gmail.users.return_value.messages.return_value.get.return_value.execute.return_value = (
        make_raw_message()
    )

    result = t.list_emails_by_age(cursor=0)

    assert len(result["emails"]) == 10
    assert result["next_cursor"] == 10


def test_list_emails_by_age_last_page(tools, mock_gmail, tmp_path, config):
    import json
    from gmail_tool.tools import GmailTools
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"message_ids": [f"id{i}" for i in range(25)]}))
    config.state_file = str(state_file)
    config.scan_page_size = 10
    t = GmailTools(mock_gmail, MagicMock(), config, "me@gmail.com")

    mock_gmail.users.return_value.messages.return_value.get.return_value.execute.return_value = (
        make_raw_message()
    )

    result = t.list_emails_by_age(cursor=20)

    assert len(result["emails"]) == 5
    assert result["next_cursor"] is None


def test_list_emails_by_age_requires_initialized_state(tools, tmp_path, config):
    from gmail_tool.tools import GmailTools
    config.state_file = str(tmp_path / "missing.json")
    t = GmailTools(MagicMock(), MagicMock(), config, "me@gmail.com")

    with pytest.raises(RuntimeError, match="initialize()"):
        t.list_emails_by_age(cursor=0)


# -------------------------------------------------------------------------
# GmailTools: excluded labels query
# -------------------------------------------------------------------------

def test_excluded_labels_query(tools):
    assert tools._excluded_labels_query() == "-label:Long-Term -label:Legal"


def test_excluded_labels_query_empty(mock_gmail, mock_drive):
    from gmail_tool.config import Config
    from gmail_tool.tools import GmailTools
    t = GmailTools(mock_gmail, mock_drive, Config(), "me@gmail.com")
    assert t._excluded_labels_query() == ""


# -------------------------------------------------------------------------
# GmailTools: label management
# -------------------------------------------------------------------------

def test_get_or_create_label_creates_when_missing(tools, mock_gmail):
    mock_gmail.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": []
    }
    mock_gmail.users.return_value.labels.return_value.create.return_value.execute.return_value = {
        "id": "Label_new"
    }

    label_id = tools._get_or_create_label("New-Label")

    assert label_id == "Label_new"
    mock_gmail.users.return_value.labels.return_value.create.assert_called_once()


def test_get_or_create_label_returns_existing(tools, mock_gmail):
    mock_gmail.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"name": "Long-Term", "id": "Label_456"}]
    }

    label_id = tools._get_or_create_label("Long-Term")

    assert label_id == "Label_456"
    mock_gmail.users.return_value.labels.return_value.create.assert_not_called()


def test_get_or_create_label_caches_result(tools, mock_gmail):
    mock_gmail.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"name": "Long-Term", "id": "Label_456"}]
    }

    tools._get_or_create_label("Long-Term")
    tools._get_or_create_label("Long-Term")

    assert mock_gmail.users.return_value.labels.return_value.list.return_value.execute.call_count == 1


# -------------------------------------------------------------------------
# GmailTools: email parsing
# -------------------------------------------------------------------------

def test_parse_email_list_item(tools):
    msg = make_raw_message(
        from_="John Doe <john@example.com>",
        to="list@example.com, me@gmail.com",
        cc="boss@example.com",
        subject="Meeting notes",
        size=2048,
    )
    item = tools._parse_email_list_item(msg)

    assert item.message_id == "msg1"
    assert item.thread_id == "thread1"
    assert item.from_address == "john@example.com"
    assert "list@example.com" in item.to
    assert "me@gmail.com" in item.to
    assert item.cc == ["boss@example.com"]
    assert item.subject == "Meeting notes"
    assert item.gmail_size_bytes == 2048


def test_parse_email_bcc_true_when_not_in_to_or_cc(tools):
    msg = make_raw_message(to="list@example.com", cc="")
    parsed = tools._parse_email(msg)
    assert parsed.bcc is True  # me@gmail.com not in to or cc


def test_parse_email_bcc_false_when_in_to(tools):
    msg = make_raw_message(to="me@gmail.com, list@example.com")
    parsed = tools._parse_email(msg)
    assert parsed.bcc is False


def test_parse_email_bcc_false_when_in_cc(tools):
    msg = make_raw_message(to="list@example.com", cc="me@gmail.com")
    parsed = tools._parse_email(msg)
    assert parsed.bcc is False


def test_parse_email_body(tools):
    data = base64.urlsafe_b64encode(b"Email body text").decode()
    msg = make_raw_message(body_data=data)
    parsed = tools._parse_email(msg)
    assert parsed.body == "Email body text"


def test_parse_email_attachments(tools):
    parts = [
        {
            "filename": "doc.pdf",
            "mimeType": "application/pdf",
            "body": {"size": 5000},
            "parts": [],
        }
    ]
    msg = make_raw_message(parts=parts)
    parsed = tools._parse_email(msg)
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].filename == "doc.pdf"


# -------------------------------------------------------------------------
# GmailTools: trash_emails
# -------------------------------------------------------------------------

def test_trash_emails_success(tools, mock_gmail):
    result = tools.trash_emails(["id1", "id2"])
    assert result["trashed_count"] == 2
    assert result["failed_ids"] == []


def test_trash_emails_partial_failure(tools, mock_gmail):
    execute_mock = MagicMock()
    execute_mock.side_effect = [None, Exception("API error")]
    mock_gmail.users.return_value.messages.return_value.trash.return_value.execute = execute_mock

    result = tools.trash_emails(["good_id", "bad_id"])

    assert result["trashed_count"] == 1
    assert result["failed_ids"] == ["bad_id"]


def test_trash_emails_all_fail(tools, mock_gmail):
    mock_gmail.users.return_value.messages.return_value.trash.return_value.execute.side_effect = (
        Exception("API error")
    )

    result = tools.trash_emails(["id1", "id2"])

    assert result["trashed_count"] == 0
    assert set(result["failed_ids"]) == {"id1", "id2"}


# -------------------------------------------------------------------------
# GmailTools: label_emails
# -------------------------------------------------------------------------

def test_label_emails_success(tools, mock_gmail):
    mock_gmail.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"name": "Long-Term", "id": "Label_1"}]
    }

    result = tools.label_emails(["id1", "id2"], "Long-Term")
    assert result["labeled_count"] == 2
    assert result["failed_ids"] == []


def test_label_emails_partial_failure(tools, mock_gmail):
    mock_gmail.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"name": "Long-Term", "id": "Label_1"}]
    }

    execute_mock = MagicMock()
    execute_mock.side_effect = [None, Exception("API error")]
    mock_gmail.users.return_value.messages.return_value.modify.return_value.execute = execute_mock

    result = tools.label_emails(["good_id", "bad_id"], "Long-Term")

    assert result["labeled_count"] == 1
    assert result["failed_ids"] == ["bad_id"]


def test_label_emails_creates_missing_label(tools, mock_gmail):
    mock_gmail.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": []
    }
    mock_gmail.users.return_value.labels.return_value.create.return_value.execute.return_value = {
        "id": "Label_new"
    }

    result = tools.label_emails(["id1"], "New-Label")

    assert result["labeled_count"] == 1
    mock_gmail.users.return_value.labels.return_value.create.assert_called_once()


# -------------------------------------------------------------------------
# GmailTools: get_emails
# -------------------------------------------------------------------------

def test_get_emails_success(tools, mock_gmail):
    msg = make_raw_message()
    mock_gmail.users.return_value.messages.return_value.get.return_value.execute.return_value = msg

    result = tools.get_emails(["msg1"])

    assert len(result["emails"]) == 1
    assert result["failed_ids"] == []


def test_get_emails_partial_failure(tools, mock_gmail):
    msg = make_raw_message()
    execute_mock = MagicMock()
    execute_mock.side_effect = [msg, Exception("not found")]
    mock_gmail.users.return_value.messages.return_value.get.return_value.execute = execute_mock

    result = tools.get_emails(["good_id", "bad_id"])

    assert len(result["emails"]) == 1
    assert result["failed_ids"] == ["bad_id"]
