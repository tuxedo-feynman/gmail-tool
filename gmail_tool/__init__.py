from .auth import get_gmail_service, get_drive_service
from .config import load_config
from .tools import GmailTools


def create_tools(config_path: str = "config.yaml") -> GmailTools:
    config = load_config(config_path)
    gmail_service = get_gmail_service(config.credentials_path, config.token_path)
    drive_service = get_drive_service(config.credentials_path, config.token_path)
    profile = gmail_service.users().getProfile(userId="me").execute()
    user_email = profile["emailAddress"]
    return GmailTools(gmail_service, drive_service, config, user_email)
