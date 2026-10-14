"""The server must accept the SAS Viya MCP's variable names as aliases, so the
RAM environment table from that template can be copied unchanged, and must
report which grant it will use."""

import importlib

from sas_vi_mcp import config

_ALL = ("VI_ENDPOINT", "VIYA_ENDPOINT", "VI_CLIENT_ID", "CLIENT_ID",
        "VI_CLIENT_SECRET", "CLIENT_SECRET", "VI_REFRESH_TOKEN",
        "VIYA_REFRESH_TOKEN", "VI_USERNAME", "VIYA_USERNAME", "VI_PASSWORD",
        "VIYA_PASSWORD", "VI_SSL_VERIFY", "SSL_VERIFY")


def _reload(monkeypatch, **env):
    for name in _ALL:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    return importlib.reload(config)


def test_viya_names_are_accepted(monkeypatch):
    cfg = _reload(monkeypatch, VIYA_ENDPOINT="https://vi.example.com/",
                  VIYA_REFRESH_TOKEN=" RT \n", CLIENT_ID="sas-mcp",
                  CLIENT_SECRET="s", SSL_VERIFY="false")
    assert cfg.VI_ENDPOINT == "https://vi.example.com"
    assert cfg.VI_REFRESH_TOKEN == "RT"
    assert cfg.VI_CLIENT_ID == "sas-mcp"
    assert cfg.VI_CLIENT_SECRET == "s"
    assert cfg.VI_SSL_VERIFY is False
    assert cfg.auth_mode() == "refresh_token"
    assert cfg.configured() is True


def test_vi_names_win_over_aliases(monkeypatch):
    cfg = _reload(monkeypatch, VI_ENDPOINT="https://vi", VIYA_ENDPOINT="https://viya",
                  VI_CLIENT_ID="sas-vi-mcp", CLIENT_ID="sas-mcp",
                  VI_SSL_VERIFY="true", SSL_VERIFY="false")
    assert cfg.VI_ENDPOINT == "https://vi"
    assert cfg.VI_CLIENT_ID == "sas-vi-mcp"
    assert cfg.VI_SSL_VERIFY is True


def test_defaults_and_password_mode(monkeypatch):
    cfg = _reload(monkeypatch, VI_ENDPOINT="https://vi", VI_USERNAME="u",
                  VI_PASSWORD="p")
    assert cfg.VI_CLIENT_ID == "sas.cli"
    assert cfg.VI_SSL_VERIFY is True
    assert cfg.auth_mode() == "password"


def test_refresh_token_takes_precedence_over_password(monkeypatch):
    cfg = _reload(monkeypatch, VI_ENDPOINT="https://vi", VI_USERNAME="u",
                  VI_PASSWORD="p", VI_REFRESH_TOKEN="RT")
    assert cfg.auth_mode() == "refresh_token"


def test_unconfigured(monkeypatch):
    cfg = _reload(monkeypatch, VI_ENDPOINT="https://vi")
    assert cfg.auth_mode() == "none"
    assert cfg.configured() is False
    _reload(monkeypatch)  # leave the module in a clean state for other tests
