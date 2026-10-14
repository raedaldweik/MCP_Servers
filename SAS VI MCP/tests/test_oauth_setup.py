"""Unit tests for the one-time OAuth helpers (vi-get-refresh-token,
vi-register-client) — pure helpers plus the HTTP paths against a mock
SAS Logon. No network."""

import base64
import hashlib
import json
import urllib.parse
from datetime import UTC, datetime

import httpx
import pytest

from sas_vi_mcp import oauth_setup
from sas_vi_mcp.oauth_setup import (
    CALLBACK_PATH,
    OOB_REDIRECT_URI,
    OAuthSetupError,
    authorize_url,
    env_lines,
    exchange_code,
    jwt_expiry,
    password_grant_token,
    pkce_pair,
    register_client,
    registration_payload,
    token_request,
)


def _mock_logon(monkeypatch, handler):
    """Route every httpx.Client the module opens through ``handler``."""
    def factory(verify):
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)
    monkeypatch.setattr(oauth_setup, "_client", factory)


def _jwt(claims: dict) -> str:
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"


# --- pure helpers -----------------------------------------------------------

def test_pkce_pair_is_s256():
    verifier, challenge = pkce_pair()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected
    assert "=" not in verifier and len(verifier) >= 43


def test_authorize_url_code_on_page_omits_redirect():
    url = authorize_url("https://vi.example.com/", "sas.cli", "CH", "ST")
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(parsed.query)
    assert parsed.path == "/SASLogon/oauth/authorize"
    assert q["client_id"] == ["sas.cli"]
    assert q["response_type"] == ["code"]
    assert q["code_challenge"] == ["CH"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["state"] == ["ST"]
    assert "redirect_uri" not in q


def test_authorize_url_with_localhost_callback():
    url = authorize_url("https://vi.example.com", "sas-vi-mcp", "CH", "ST",
                        f"http://localhost:8141{CALLBACK_PATH}")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["redirect_uri"] == ["http://localhost:8141/auth/callback"]


def test_token_request_public_client_has_no_basic_auth():
    data, auth = token_request({"grant_type": "refresh_token"}, "sas.cli")
    assert data == {"grant_type": "refresh_token", "client_id": "sas.cli"}
    assert auth is None


def test_token_request_confidential_client_uses_basic_auth():
    _, auth = token_request({"grant_type": "x"}, "cid", "secret")
    assert auth == ("cid", "secret")


def test_registration_payload_defaults():
    p = registration_payload("sas-vi-mcp", 8141, 365 * 86400)
    assert p["authorized_grant_types"] == ["authorization_code", "refresh_token"]
    assert p["redirect_uri"] == [OOB_REDIRECT_URI,
                                 "http://localhost:8141/auth/callback"]
    assert p["allowpublic"] is True and p["autoapprove"] is True
    assert p["refresh-token-validity"] == 31536000
    assert "client_secret" not in p


def test_registration_payload_confidential():
    p = registration_payload("cid", 8141, 10, client_secret="s3")
    assert p["client_secret"] == "s3" and p["allowpublic"] is False


def test_jwt_expiry_reads_exp_and_tolerates_opaque_tokens():
    assert jwt_expiry(_jwt({"exp": 1_900_000_000})) == datetime.fromtimestamp(
        1_900_000_000, tz=UTC)
    assert jwt_expiry("not-a-jwt") is None
    assert jwt_expiry(_jwt({"sub": "x"})) is None


def test_env_lines_match_server_variable_names():
    text = env_lines("https://vi", "sas.cli", "RT")
    assert text.splitlines() == ["VI_ENDPOINT=https://vi",
                                 "VI_CLIENT_ID=sas.cli",
                                 "VI_REFRESH_TOKEN=RT"]


# --- exchange_code ----------------------------------------------------------

def test_exchange_code_sends_pkce_and_returns_tokens(monkeypatch):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["form"] = urllib.parse.parse_qs(request.content.decode())
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"access_token": "AT",
                                         "refresh_token": "RT",
                                         "expires_in": 3600})

    _mock_logon(monkeypatch, handler)
    body = exchange_code("https://vi.example.com/", "sas.cli", "", "CODE",
                         "VERIFIER", None, verify=False)
    assert body["refresh_token"] == "RT"
    assert seen["url"] == "https://vi.example.com/SASLogon/oauth/token"
    assert seen["form"]["grant_type"] == ["authorization_code"]
    assert seen["form"]["code"] == ["CODE"]
    assert seen["form"]["code_verifier"] == ["VERIFIER"]
    assert seen["form"]["client_id"] == ["sas.cli"]
    assert "redirect_uri" not in seen["form"]
    assert seen["auth"] is None


def test_exchange_code_retries_with_empty_secret_basic_on_401(monkeypatch):
    attempts = []

    def handler(request: httpx.Request):
        attempts.append(request.headers.get("authorization"))
        if len(attempts) == 1:
            return httpx.Response(401, json={"error": "invalid_client"})
        return httpx.Response(200, json={"access_token": "AT",
                                         "refresh_token": "RT"})

    _mock_logon(monkeypatch, handler)
    body = exchange_code("https://vi", "sas.cli", "", "C", "V",
                         "http://localhost:8141/auth/callback", verify=False)
    assert body["refresh_token"] == "RT"
    assert attempts[0] is None
    assert attempts[1] == "Basic " + base64.b64encode(b"sas.cli:").decode()


def test_exchange_code_rejects_missing_refresh_token(monkeypatch):
    _mock_logon(monkeypatch, lambda r: httpx.Response(200, json={"access_token": "AT"}))
    with pytest.raises(OAuthSetupError, match="no refresh token"):
        exchange_code("https://vi", "cid", "", "C", "V", None, verify=False)


def test_exchange_code_reports_http_failure(monkeypatch):
    _mock_logon(monkeypatch, lambda r: httpx.Response(400, text="invalid_grant"))
    with pytest.raises(OAuthSetupError, match="HTTP 400 invalid_grant"):
        exchange_code("https://vi", "cid", "", "C", "V", None, verify=False)


# --- registration -----------------------------------------------------------

def test_password_grant_token_uses_sas_cli_basic(monkeypatch):
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers.get("authorization")
        seen["form"] = urllib.parse.parse_qs(request.content.decode())
        return httpx.Response(200, json={"access_token": "ADMIN"})

    _mock_logon(monkeypatch, handler)
    assert password_grant_token("https://vi", "sasboot", "pw", verify=False) == "ADMIN"
    assert seen["auth"] == "Basic " + base64.b64encode(b"sas.cli:").decode()
    assert seen["form"]["grant_type"] == ["password"]


def test_password_grant_token_explains_sso_failure(monkeypatch):
    _mock_logon(monkeypatch, lambda r: httpx.Response(401, text="unauthorized"))
    with pytest.raises(OAuthSetupError, match="--admin-token"):
        password_grant_token("https://vi", "me@corp.com", "pw", verify=False)


def test_register_client_replaces_and_verifies(monkeypatch):
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer ADMIN"
        if request.method == "DELETE":
            return httpx.Response(404)
        if request.method == "POST":
            assert json.loads(request.content)["client_id"] == "sas-vi-mcp"
            return httpx.Response(201, json={})
        return httpx.Response(200, json={"client_id": "sas-vi-mcp",
                                         "refresh-token-validity": 42})

    _mock_logon(monkeypatch, handler)
    payload = registration_payload("sas-vi-mcp", 8141, 42)
    result = register_client("https://vi", "ADMIN", payload, verify=False)
    assert result["refresh-token-validity"] == 42
    assert calls == [("DELETE", "/SASLogon/oauth/clients/sas-vi-mcp"),
                     ("POST", "/SASLogon/oauth/clients"),
                     ("GET", "/SASLogon/oauth/clients/sas-vi-mcp")]


def test_register_client_reports_forbidden(monkeypatch):
    def handler(request: httpx.Request):
        if request.method == "DELETE":
            return httpx.Response(404)
        return httpx.Response(403, text="forbidden")

    _mock_logon(monkeypatch, handler)
    with pytest.raises(OAuthSetupError, match="HTTP 403"):
        register_client("https://vi", "T", registration_payload("c", 1, 1), False)


# --- CLI ----------------------------------------------------------------------

def test_get_refresh_token_cli_two_step_flow(monkeypatch, tmp_path, capsys):
    """Non-interactive terminal: first run saves PKCE state and prints the
    URL; the --code run exchanges it and prints the RAM variables."""
    monkeypatch.setattr(oauth_setup, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(oauth_setup.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(oauth_setup.webbrowser, "open", lambda url: True)

    rc = oauth_setup.get_refresh_token_main(
        ["--endpoint", "https://vi.example.com/", "--client-id", "sas.cli",
         "--insecure"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "https://vi.example.com/SASLogon/oauth/authorize?" in out
    assert "--code <CODE>" in out
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["client_id"] == "sas.cli"

    seen = {}

    def handler(request: httpx.Request):
        seen["form"] = urllib.parse.parse_qs(request.content.decode())
        return httpx.Response(200, json={"access_token": "AT",
                                         "refresh_token": _jwt({"exp": 1_900_000_000}),
                                         "expires_in": 3600})

    _mock_logon(monkeypatch, handler)
    rc = oauth_setup.get_refresh_token_main(
        ["--endpoint", "https://vi.example.com", "--code", "ABC", "--insecure"])
    assert rc == 0
    out = capsys.readouterr().out
    assert seen["form"]["code_verifier"] == [state["verifier"]]
    assert "VI_ENDPOINT=https://vi.example.com" in out
    assert "VI_CLIENT_ID=sas.cli" in out
    assert "VI_REFRESH_TOKEN=" in out
    assert "valid until 2030-03-17" in out
    assert not (tmp_path / "state.json").exists()


def test_get_refresh_token_cli_requires_endpoint(monkeypatch):
    monkeypatch.setattr(oauth_setup.config, "VI_ENDPOINT", "")
    with pytest.raises(SystemExit):
        oauth_setup.get_refresh_token_main([])
