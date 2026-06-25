import logging
from pathlib import Path

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Config(BaseModel):
    excluded_labels: list[str] = []
    scan_page_size: int = 100
    sender_page_size: int = 50
    credentials_file: str = "~/.gmail-tool/credentials.json"
    oauth_token_file: str = "~/.gmail-tool/token.json"
    state_file: str = "~/.gmail-tool/state.json"

    @property
    def credentials_path(self) -> Path:
        return Path(self.credentials_file).expanduser()

    @property
    def token_path(self) -> Path:
        return Path(self.oauth_token_file).expanduser()

    @property
    def state_path(self) -> Path:
        return Path(self.state_file).expanduser()


def load_config(path: str = "config.yaml") -> Config:
    config_path = Path(path)
    if not config_path.exists():
        logger.warning("Config file not found at %s, using defaults", path)
        return Config()
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return Config(**data)
