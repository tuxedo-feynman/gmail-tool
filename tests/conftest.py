import pytest
from unittest.mock import MagicMock

from gmail_tool.config import Config
from gmail_tool.tools import GmailTools


@pytest.fixture
def config():
    return Config(
        excluded_labels=["Long-Term", "Legal"],
        scan_page_size=10,
        sender_page_size=5,
    )


@pytest.fixture
def mock_gmail():
    return MagicMock()


@pytest.fixture
def mock_drive():
    return MagicMock()


@pytest.fixture
def tools(mock_gmail, mock_drive, config):
    return GmailTools(mock_gmail, mock_drive, config, "me@gmail.com")


def make_raw_message(
    msg_id="msg1",
    thread_id="thread1",
    from_="Sender <sender@example.com>",
    to="list@example.com",
    cc="",
    subject="Test Subject",
    date="Mon, 1 Jan 2024 12:00:00 +0000",
    size=1024,
    labels=None,
    body_data="",
    parts=None,
):
    payload = {
        "mimeType": "text/plain",
        "headers": [
            {"name": "From", "value": from_},
            {"name": "To", "value": to},
            {"name": "Cc", "value": cc},
            {"name": "Subject", "value": subject},
            {"name": "Date", "value": date},
        ],
        "body": {"data": body_data},
    }
    if parts is not None:
        payload["mimeType"] = "multipart/mixed"
        payload["parts"] = parts

    return {
        "id": msg_id,
        "threadId": thread_id,
        "sizeEstimate": size,
        "labelIds": labels or [],
        "payload": payload,
    }
