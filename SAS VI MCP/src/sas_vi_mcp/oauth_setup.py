"""One-time OAuth helpers for running this server headless in SAS Retrieval
Agent Manager — the same recipe as the SAS Viya MCP's ``examples/`` scripts.

Two console scripts (also runnable as ``examples/*.py``):

``vi-get-refresh-token``
    Sign in to the Visual Investigator environment's SAS Logon **once** in a
    browser (authorization-code flow with PKCE) and print the
    ``VI_REFRESH_TOKEN`` line to paste into the RAM template as a secret.
    The server then exchanges that token for access tokens on its own, with
    the full identity of the user who signed in — no browser and no stored
    password afterwards. Works for SSO/federated identities (where the
    password grant cannot) and for local accounts alike.

    With the default ``sas-mcp`` client (the one the SAS Viya MCP registers)
    the browser is redirected to ``http://localhost:8134/auth/callback``,
    exactly like that repo's ``get_refresh_token.py``. With a built-in client
    (``--client-id sas.cli`` or ``vscode``, no registration needed) no
    redirect URI is sent and SAS Logon shows the authorization code on a
    results page for you to paste back; ``--code-on-page`` forces that mode
    and ``--callback-port`` forces the redirect mode.

``vi-register-client``
    (Admin, once per Viya deployment.) Register the ``sas-mcp`` client on
    the VI environment with the same definition as the SAS Viya MCP's
    ``register_mcp_client.py`` — authorization_code + refresh_token grants,
    the localhost:8134 redirect URI and a one-year refresh-token validity —
    so the one-time login is rarely repeated. Skip it when VI runs on the
    same Viya where ``sas-mcp`` already exists. Needs an account SAS Logon
    can authenticate directly (``sasboot`` or a local admin) or an existing
    admin bearer token.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import getpass
import hashlib
import json
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

from . import config

OOB_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
CALLBACK_PATH = "/auth/callback"
# Same client id and redirect port as the SAS Viya MCP's register_mcp_client.py,
# so the client definition is identical on both environments.
DEFAULT_REGISTERED_CLIENT_ID = "sas-mcp"
DEFAULT_CALLBACK_PORT = 8134
# Clients that ship with Viya and support the code-on-page flow (no
# redirect URI registered for localhost).
BUILTIN_CLIENTS = frozenset({"sas.cli", "vscode"})
# PKCE state for the two-step (non-interactive terminal) variant of
# vi-get-refresh-token, mirroring the SAS Viya MCP's sas-mcp-login helper.
STATE_PATH = Path.home() / ".sas-vi-mcp" / "login-state.json"

_FORM = {"Content-Type": "application/x-www-form-urlencoded"}


class OAuthSetupError(RuntimeError):
    """A failure with an operator-facing message (printed, exit code 1)."""


# --- Pure helpers (unit-tested) --------------------------------------------

def pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for the S256 PKCE method."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(endpoint: str, client_id: str, challenge: str, state: str,
                  redirect_uri: str | None = None) -> str:
    """Build the SAS Logon authorization URL. Without ``redirect_uri`` SAS
    Logon displays the code on a page instead of redirecting. No ``scope``
    is requested, so SAS Logon grants the client's own scopes — this works
    for any client (sas.cli, vscode, a registered one) instead of failing
    with invalid_scope on a client that lacks ``openid``."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    return (f"{endpoint.rstrip('/')}/SASLogon/oauth/authorize?"
            + urllib.parse.urlencode(params))


def resolve_redirect_uri(client_id: str, callback_port: int | None,
                         code_on_page: bool) -> str | None:
    """Pick the sign-in mode: ``None`` means code-on-page (no redirect URI);
    otherwise the localhost callback URI. Explicit flags win; a built-in
    client defaults to code-on-page, a registered one (sas-mcp) to the
    localhost:8134 callback it was registered with."""
    if code_on_page:
        return None
    if callback_port:
        return f"http://localhost:{callback_port}{CALLBACK_PATH}"
    if client_id in BUILTIN_CLIENTS:
        return None
    return f"http://localhost:{DEFAULT_CALLBACK_PORT}{CALLBACK_PATH}"


def token_request(grant: dict, client_id: str, client_secret: str = ""
                  ) -> tuple[dict, tuple[str, str] | None]:
    """Return ``(form_data, basic_auth)`` for ``/SASLogon/oauth/token``.

    Public clients send ``client_id`` in the body with no Basic header;
    confidential clients authenticate with HTTP Basic.
    """
    data = {**grant, "client_id": client_id}
    auth = (client_id, client_secret) if client_secret else None
    return data, auth


def registration_payload(client_id: str, callback_port: int,
                         validity_seconds: int, client_secret: str = "") -> dict:
    """Client registration body: authorization_code + refresh_token grants,
    both redirect styles (code-on-page and localhost callback), long
    refresh-token validity."""
    payload: dict = {
        "client_id": client_id,
        "scope": ["openid"],
        "authorized_grant_types": ["authorization_code", "refresh_token"],
        "redirect_uri": [OOB_REDIRECT_URI,
                         f"http://localhost:{callback_port}{CALLBACK_PATH}"],
        "autoapprove": True,
        "allowpublic": True,
        "access-token-validity": 36000,
        "refresh-token-validity": validity_seconds,
    }
    if client_secret:
        payload["client_secret"] = client_secret
        payload["allowpublic"] = False
    return payload


def jwt_expiry(token: str) -> datetime | None:
    """Best-effort ``exp`` of a JWT-shaped token (SAS Logon issues JWTs), so
    the operator knows when the refresh token will need renewing."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
    except Exception:
        return None


def env_lines(endpoint: str, client_id: str, refresh_token: str) -> str:
    """The exact lines to paste into the RAM template (or a .env file)."""
    return "\n".join([
        f"VI_ENDPOINT={endpoint}",
        f"VI_CLIENT_ID={client_id}",
        f"VI_REFRESH_TOKEN={refresh_token}",
    ])


# --- HTTP ------------------------------------------------------------------

def _client(verify: bool) -> httpx.Client:
    return httpx.Client(verify=verify, timeout=60.0)


def exchange_code(endpoint: str, client_id: str, client_secret: str, code: str,
                  verifier: str, redirect_uri: str | None, verify: bool) -> dict:
    """Swap an authorization code for tokens; the response must carry a
    refresh token or the client is not registered for that grant."""
    grant = {"grant_type": "authorization_code", "code": code,
             "code_verifier": verifier}
    if redirect_uri:
        grant["redirect_uri"] = redirect_uri
    data, auth = token_request(grant, client_id, client_secret)
    url = f"{endpoint.rstrip('/')}/SASLogon/oauth/token"
    try:
        with _client(verify) as http:
            resp = http.post(url, auth=auth, headers=_FORM, data=data)
            if resp.status_code == 401 and not client_secret:
                # Some SAS Logon setups (sas.cli on RACE) want the
                # empty-secret Basic form for public clients.
                resp = http.post(url, auth=(client_id, ""), headers=_FORM,
                                 data=grant)
    except httpx.HTTPError as exc:
        raise OAuthSetupError(f"Could not reach SAS Logon at {url}: {exc}") from exc
    if resp.status_code != 200:
        raise OAuthSetupError(
            f"Token exchange failed: HTTP {resp.status_code} {resp.text[:400]}\n"
            "Check that the code was pasted completely (it is single-use and "
            "short-lived) and that --client-id matches the client used in the "
            "browser.")
    body = resp.json()
    if not body.get("refresh_token"):
        raise OAuthSetupError(
            f"SAS Logon returned no refresh token for client '{client_id}'. "
            "The client must have the 'refresh_token' grant type — register "
            "one with `vi-register-client`, or use the built-in 'sas.cli'.")
    return body


def password_grant_token(endpoint: str, username: str, password: str,
                         verify: bool, client_id: str = "sas.cli") -> str:
    """Admin access token for client registration (password grant)."""
    url = f"{endpoint.rstrip('/')}/SASLogon/oauth/token"
    try:
        with _client(verify) as http:
            resp = http.post(url, auth=(client_id, ""), headers=_FORM,
                             data={"grant_type": "password",
                                   "username": username, "password": password})
    except httpx.HTTPError as exc:
        raise OAuthSetupError(f"Could not reach SAS Logon at {url}: {exc}") from exc
    if resp.status_code != 200:
        raise OAuthSetupError(
            f"Admin sign-in failed: HTTP {resp.status_code} {resp.text[:300]}\n"
            "The password grant only works for accounts SAS Logon "
            "authenticates directly (sasboot / a local admin). For an SSO "
            "admin, pass --admin-token with a bearer token instead.")
    return resp.json()["access_token"]


def register_client(endpoint: str, admin_token: str, payload: dict,
                    verify: bool) -> dict:
    """Delete any client with the same id, register the new one, and return
    SAS Logon's view of it."""
    base = f"{endpoint.rstrip('/')}/SASLogon/oauth/clients"
    headers = {"Authorization": f"Bearer {admin_token}"}
    client_id = payload["client_id"]
    try:
        with _client(verify) as http:
            existing = http.delete(f"{base}/{client_id}", headers=headers)
            if existing.status_code not in (200, 404):
                raise OAuthSetupError(
                    f"Could not replace existing client '{client_id}': HTTP "
                    f"{existing.status_code} {existing.text[:300]}")
            if existing.status_code == 200:
                print(f"Replaced existing client '{client_id}'.")
            created = http.post(base, headers={**headers,
                                               "Content-Type": "application/json"},
                                json=payload)
            if created.status_code not in (200, 201):
                raise OAuthSetupError(
                    f"Client registration failed: HTTP {created.status_code} "
                    f"{created.text[:400]}\nThe account needs authority to "
                    "manage OAuth clients (a SAS Administrator, or the "
                    "environment's Consul token as --admin-token).")
            check = http.get(f"{base}/{client_id}", headers=headers)
    except httpx.HTTPError as exc:
        raise OAuthSetupError(f"Could not reach SAS Logon at {base}: {exc}") from exc
    return check.json() if check.status_code == 200 else payload


# --- Local callback server (for --callback-port) ---------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        self.server.query = urllib.parse.parse_qs(parsed.query)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in self.server.query  # type: ignore[attr-defined]
        msg = ("Sign-in complete. You can close this tab and return to the "
               "terminal." if ok else
               "Sign-in failed. Check the terminal for details.")
        self.wfile.write(
            f"<html><body style='font-family:sans-serif;padding:2rem'>"
            f"<h3>SAS Visual Investigator MCP</h3><p>{msg}</p></body></html>"
            .encode())
        self.server.done.set()  # type: ignore[attr-defined]

    def log_message(self, *args):  # silence default request logging
        pass


def await_localhost_redirect(port: int, timeout: int = 300) -> dict:
    """Serve one request on localhost:port and return its query params."""
    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.query = {}  # type: ignore[attr-defined]
    server.done = threading.Event()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not server.done.wait(timeout=timeout):  # type: ignore[attr-defined]
            raise OAuthSetupError(
                f"Timed out after {timeout}s waiting for the browser redirect. "
                "If SAS Logon showed the login page but never redirected to "
                "localhost, its form-action Content-Security-Policy is "
                "blocking it — re-run with --code-on-page (works with a client "
                "registered by vi-register-client, or with sas.cli/vscode).")
    finally:
        server.shutdown()
        thread.join()
    return server.query  # type: ignore[attr-defined]


# --- Two-step state (non-interactive terminals) -----------------------------

def _write_state(payload: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload))
    with contextlib.suppress(OSError):
        os.chmod(STATE_PATH, 0o600)


def _read_state() -> dict | None:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _clear_state() -> None:
    with contextlib.suppress(OSError):
        STATE_PATH.unlink()


# --- Output ----------------------------------------------------------------

def _print_success(endpoint: str, client_id: str, tokens: dict) -> None:
    refresh = tokens["refresh_token"]
    print()
    print("=" * 72)
    print("SUCCESS. In the RAM template (Code Templates > Tools > your VI tool)")
    print("open the Environment Variables tab and set these — mark VI_ENDPOINT")
    print("and VI_REFRESH_TOKEN as Secret, exactly like the SAS Viya MCP:")
    print()
    for line in env_lines(endpoint, client_id, refresh).splitlines():
        print(f"  {line}")
    print()
    expiry = jwt_expiry(refresh)
    if expiry:
        print(f"  Refresh token valid until {expiry:%Y-%m-%d %H:%M} UTC "
              "(re-run this helper before then and update the secret).")
    else:
        print("  The refresh token's lifetime is the client's "
              "refresh-token-validity; re-run this helper when it expires.")
    print(f"  (access tokens last {tokens.get('expires_in', '?')}s and are "
          "renewed by the server automatically)")
    print("=" * 72)


def _verify_flag(insecure: bool) -> bool:
    return False if insecure else config.VI_SSL_VERIFY


# --- Entry points ----------------------------------------------------------

def get_refresh_token_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vi-get-refresh-token",
        description=("Sign in to Visual Investigator once in a browser and "
                     "print the VI_REFRESH_TOKEN for a headless (RAM) "
                     "deployment."))
    parser.add_argument("--endpoint", default=config.VI_ENDPOINT,
                        help="VI base URL (default: VI_ENDPOINT / VIYA_ENDPOINT)")
    parser.add_argument("--client-id", default=config.VI_CLIENT_ID,
                        help="OAuth client to sign in with (default: VI_CLIENT_ID "
                             "/ CLIENT_ID, else 'sas-mcp'). The server must run "
                             "with the same VI_CLIENT_ID.")
    parser.add_argument("--client-secret", default=config.VI_CLIENT_SECRET,
                        help="Only for a confidential client (default: "
                             "VI_CLIENT_SECRET / CLIENT_SECRET)")
    parser.add_argument("--callback-port", type=int, default=None,
                        help="Port of the localhost redirect URI the client "
                             f"was registered with (default {DEFAULT_CALLBACK_PORT} "
                             "for sas-mcp and other registered clients)")
    parser.add_argument("--code-on-page", action="store_true",
                        help="Send no redirect URI; SAS Logon shows the code on "
                             "a page to paste back (default for the built-in "
                             "sas.cli / vscode clients)")
    parser.add_argument("--code", default="",
                        help="Finish a login started in a non-interactive "
                             "terminal: pass the code SAS Logon displayed.")
    parser.add_argument("--no-browser", action="store_true",
                        help="Print the sign-in URL without opening a browser")
    parser.add_argument("--insecure", action="store_true",
                        help="Skip TLS verification (RACE/Engage images, "
                             "cloudflared quick tunnels)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Seconds to wait for the browser (default 300)")
    args = parser.parse_args(argv)

    if not args.endpoint:
        parser.error("VI_ENDPOINT is not set and --endpoint was not given")
    endpoint = args.endpoint.rstrip("/")
    verify = _verify_flag(args.insecure)

    try:
        if args.code:
            state = _read_state()
            if not state:
                raise OAuthSetupError(
                    f"No saved login state at {STATE_PATH}. Run "
                    "vi-get-refresh-token without --code first.")
            tokens = exchange_code(state["endpoint"], state["client_id"],
                                   args.client_secret, args.code,
                                   state["verifier"], state.get("redirect_uri"),
                                   verify)
            _clear_state()
            _print_success(state["endpoint"], state["client_id"], tokens)
            return 0

        verifier, challenge = pkce_pair()
        state_token = secrets.token_urlsafe(24)
        redirect_uri = resolve_redirect_uri(args.client_id, args.callback_port,
                                            args.code_on_page)
        callback_port = (urllib.parse.urlparse(redirect_uri).port
                         if redirect_uri else 0)
        url = authorize_url(endpoint, args.client_id, challenge, state_token,
                            redirect_uri)

        print(f"VI endpoint:  {endpoint}")
        print(f"Client ID:    {args.client_id}")
        print(f"Redirect:     {redirect_uri or '(none — SAS Logon shows the code on a page)'}")
        print(f"TLS verify:   {verify}")
        print()
        print("Step 1 — open this URL in a browser and sign in (SSO or local "
              "account):")
        print()
        print(f"  {url}")
        print()
        if not args.no_browser:
            webbrowser.open(url)

        if redirect_uri:
            print("Step 2 — waiting for SAS Logon to redirect the browser back "
                  f"to {redirect_uri} (up to {args.timeout}s)...")
            query = await_localhost_redirect(callback_port, args.timeout)
            if "error" in query:
                raise OAuthSetupError(
                    "Authorization failed: "
                    f"{query.get('error', [''])[0]} "
                    f"{query.get('error_description', [''])[0]}")
            if query.get("state", [None])[0] != state_token:
                raise OAuthSetupError(
                    "Authorization failed: state mismatch (possible CSRF).")
            code = query.get("code", [""])[0]
        else:
            print("Step 2 — after signing in, SAS Logon displays the "
                  "authorization code. Copy it.")
            print()
            if not sys.stdin.isatty():
                _write_state({"endpoint": endpoint, "client_id": args.client_id,
                              "redirect_uri": "", "verifier": verifier})
                print("This terminal cannot prompt. Once you have the code, run:")
                print()
                print(f"    vi-get-refresh-token --code <CODE>"
                      f"{' --insecure' if args.insecure else ''}")
                print()
                print(f"(PKCE state saved to {STATE_PATH})")
                return 0
            try:
                code = input("Authorization code: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                return 1
        if not code:
            raise OAuthSetupError("No authorization code received.")

        print("Exchanging the code for tokens...")
        tokens = exchange_code(endpoint, args.client_id, args.client_secret,
                               code, verifier, redirect_uri, verify)
        _print_success(endpoint, args.client_id, tokens)
        return 0
    except OAuthSetupError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


def register_client_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vi-register-client",
        description=("Register the sas-mcp OAuth client on the Visual "
                     "Investigator environment — same definition as the SAS "
                     "Viya MCP's register_mcp_client.py, with a long "
                     "refresh-token validity (admin, once per deployment)."))
    parser.add_argument("--endpoint", default=config.VI_ENDPOINT,
                        help="VI base URL (default: VI_ENDPOINT / VIYA_ENDPOINT)")
    parser.add_argument("--client-id", default=DEFAULT_REGISTERED_CLIENT_ID,
                        help=f"Client id to create (default: "
                             f"{DEFAULT_REGISTERED_CLIENT_ID}, like the SAS Viya MCP)")
    parser.add_argument("--client-secret", default="",
                        help="Make it a confidential client with this secret "
                             "(default: public/PKCE client, no secret)")
    parser.add_argument("--validity-days", type=int, default=365,
                        help="refresh-token-validity in days (default 365). "
                             "SAS Logon may cap this globally.")
    parser.add_argument("--callback-port", type=int, default=DEFAULT_CALLBACK_PORT,
                        help="Port of the localhost redirect URI (default "
                             f"{DEFAULT_CALLBACK_PORT}, the same as the SAS Viya "
                             "MCP's registration)")
    parser.add_argument("--admin-token", default=os.getenv("VI_ADMIN_TOKEN", ""),
                        help="Existing admin bearer token (default: "
                             "VI_ADMIN_TOKEN). If omitted you are prompted for "
                             "an admin username/password (password grant).")
    parser.add_argument("--admin-user", default="",
                        help="Admin username for the prompt (e.g. sasboot)")
    parser.add_argument("--insecure", action="store_true",
                        help="Skip TLS verification")
    args = parser.parse_args(argv)

    if not args.endpoint:
        parser.error("VI_ENDPOINT is not set and --endpoint was not given")
    endpoint = args.endpoint.rstrip("/")
    verify = _verify_flag(args.insecure)

    try:
        token = args.admin_token
        if not token:
            print("Sign in as a SAS administrator that SAS Logon authenticates "
                  "directly (e.g. sasboot). SSO/Okta accounts cannot use this "
                  "prompt — pass --admin-token instead.")
            username = args.admin_user or input("Admin username: ").strip()
            password = getpass.getpass("Admin password: ")
            token = password_grant_token(endpoint, username, password, verify)
            print("Authenticated.\n")

        payload = registration_payload(args.client_id, args.callback_port,
                                       args.validity_days * 86400,
                                       args.client_secret)
        result = register_client(endpoint, token, payload, verify)
        print(f"Client '{args.client_id}' is registered on {endpoint}:")
        for key in ("scope", "authorized_grant_types", "redirect_uri",
                    "autoapprove", "allowpublic", "refresh-token-validity"):
            if key in result:
                print(f"  {key}: {result[key]}")
        print()
        print("Next: obtain the refresh token with this client, then set")
        print(f"VI_CLIENT_ID={args.client_id} alongside it in the RAM template:")
        print()
        port_flag = (f" --callback-port {args.callback_port}"
                     if args.callback_port != DEFAULT_CALLBACK_PORT else "")
        print(f"    vi-get-refresh-token --client-id {args.client_id}{port_flag}"
              f"{' --insecure' if args.insecure else ''}")
        return 0
    except OAuthSetupError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(get_refresh_token_main())
