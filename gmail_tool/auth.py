import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]


def get_gmail_service(credentials_file: Path, token_file: Path):
    creds = _load_or_refresh_creds(credentials_file, token_file)
    return build("gmail", "v1", credentials=creds)


def get_drive_service(credentials_file: Path, token_file: Path):
    creds = _load_or_refresh_creds(credentials_file, token_file)
    return build("drive", "v3", credentials=creds)


def _load_or_refresh_creds(credentials_file: Path, token_file: Path) -> Credentials:
    creds = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            logger.debug("Refreshed OAuth token")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_file), SCOPES
            )
            creds = flow.run_local_server(port=0)
            logger.info("Completed OAuth flow")

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json())
        logger.debug("Saved OAuth token to %s", token_file)

    return creds
