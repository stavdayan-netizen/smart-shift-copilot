"""The local .env loader (app/config.py): a copy of .env.example must load as the README says."""
import os
import re

from app import config

EXAMPLE = config.ROOT / ".env.example"
NAMES = re.findall(r"^#?\s*([A-Z_]+)=", EXAMPLE.read_text(encoding="utf-8"), re.M)


def _clean_env(monkeypatch, names):
    # setenv first so monkeypatch records the original state and restores it after the test,
    # including removing variables the loader adds.
    for name in names:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


def test_copied_env_example_loads(monkeypatch):
    _clean_env(monkeypatch, NAMES)
    config._load_dotenv(EXAMPLE)
    s = config.load_settings()
    assert s.environment == "local"
    assert s.manager_password is None  # the example leaves it empty on purpose
    assert s.manager_name == "manager"
    assert s.session_hours == 24
    assert s.client_ip_header is None
    assert s.database_url == "sqlite:///./local.db"
    assert s.history_limit == 20
    assert s.daily_cap_usd == 3.0
    assert s.anthropic_api_key is None  # the line holds only a comment


def test_quoted_value_keeps_its_hash(tmp_path, monkeypatch):
    _clean_env(monkeypatch, ["MANAGER_PASSWORD", "TIMEZONE", "MODEL"])
    env = tmp_path / ".env"
    env.write_text('MANAGER_PASSWORD="pa ss#word"   # manager password\n'
                   "MODEL='claude-opus-5-5'\n"
                   "TIMEZONE=Asia/Jerusalem#not-a-comment\n", encoding="utf-8")
    config._load_dotenv(env)
    assert os.environ["MANAGER_PASSWORD"] == "pa ss#word"
    assert os.environ["MODEL"] == "claude-opus-5-5"
    assert os.environ["TIMEZONE"] == "Asia/Jerusalem#not-a-comment"


def _production_env(monkeypatch, **overrides):
    values = {"APP_ENV": "production", "MODEL_PROVIDER": "fake", "MANAGER_PASSWORD": "a-long-manager-password",
              "APP_SECRET": "s" * 40}
    values.update(overrides)
    for name in ("MANAGER_PASSWORD", "APP_SECRET", "APP_ENV", "MODEL_PROVIDER"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    for k, v in values.items():
        if v is not None:
            monkeypatch.setenv(k, v)


def test_production_needs_strong_secrets(monkeypatch):
    import pytest

    _production_env(monkeypatch)
    assert config.load_settings().is_production
    for override, message in (({"MANAGER_PASSWORD": None}, "MANAGER_PASSWORD"), ({"APP_SECRET": None}, "APP_SECRET"),
                              ({"MANAGER_PASSWORD": "short"}, "at least 12"), ({"APP_SECRET": "short"}, "at least 32")):
        _production_env(monkeypatch, **override)
        with pytest.raises(RuntimeError, match=message):
            config.load_settings()
