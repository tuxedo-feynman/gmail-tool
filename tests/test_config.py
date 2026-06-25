import yaml
import pytest
from gmail_tool.config import load_config, Config


def test_defaults_when_file_missing(tmp_path):
    config = load_config(str(tmp_path / "nonexistent.yaml"))
    assert config.scan_page_size == 100
    assert config.sender_page_size == 50
    assert config.excluded_labels == []


def test_loads_excluded_labels(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump({"excluded_labels": ["Long-Term", "Legal"]}))
    config = load_config(str(path))
    assert config.excluded_labels == ["Long-Term", "Legal"]


def test_loads_page_sizes(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump({"scan_page_size": 25, "sender_page_size": 10}))
    config = load_config(str(path))
    assert config.scan_page_size == 25
    assert config.sender_page_size == 10


def test_partial_config_uses_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump({"scan_page_size": 50}))
    config = load_config(str(path))
    assert config.scan_page_size == 50
    assert config.sender_page_size == 50  # default


def test_credentials_path_expands_home():
    config = Config(credentials_file="~/.gmail-tool/credentials.json")
    assert not str(config.credentials_path).startswith("~")


def test_token_path_expands_home():
    config = Config(oauth_token_file="~/.gmail-tool/token.json")
    assert not str(config.token_path).startswith("~")
