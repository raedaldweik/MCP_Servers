"""Configuration for the SAS Visual Investigator MCP server.

Everything is driven by environment variables so the container can be
configured entirely from the RAM template's Environment Variables tab
(the same convention as the SAS Viya MCP: endpoint + client + credentials,
with SSL verification switchable for tunnelled/RACE environments).

Every ``VI_*`` variable also accepts the name the SAS Viya MCP template uses
(``VIYA_ENDPOINT``, ``VIYA_REFRESH_TOKEN``, ``CLIENT_ID``, ``CLIENT_SECRET``,
``SSL_VERIFY``), so the environment table from that template can be copied
across unchanged. The ``VI_*`` name wins when both are set.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("sas_vi_mcp")


def _env(name: str, *aliases: str, default: str = "") -> str:
    """Return the first non-empty value among ``name`` and its aliases.

    Values are stripped so a secret pasted with a trailing newline or space
    (easy to do in a web form) still works.
    """
    for key in (name, *aliases):
        raw = os.getenv(key)
        if raw is not None and raw.strip() != "":
            return raw.strip()
    return default


def _bool(name: str, default: bool, *aliases: str) -> bool:
    raw = _env(name, *aliases)
    if raw == "":
        return default
    return raw.lower() not in ("false", "0", "no", "off")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        logger.warning("Invalid integer for %s — using default %s", name, default)
        return default


# --- Connection -------------------------------------------------------------
# The base URL of the Visual Investigator environment. When VI runs on a RACE
# or Engage image that RAM cannot reach directly, this is the cloudflared
# tunnel URL (e.g. https://<random>.trycloudflare.com) started with:
#   cloudflared tunnel --url https://<race-host> --no-tls-verify \
#       --http-host-header <race-host>
VI_ENDPOINT = _env("VI_ENDPOINT", "VIYA_ENDPOINT").rstrip("/")

# OAuth client used against {VI_ENDPOINT}/SASLogon/oauth/token.
# "sas-mcp" is the client the SAS Viya MCP registers (register_mcp_client.py:
# authorization_code + refresh_token grants, redirect
# http://localhost:8134/auth/callback, one-year refresh validity);
# `vi-register-client` creates the identical client on the VI environment.
# A refresh token only works with the client it was issued to, so this must
# match the client `vi-get-refresh-token` used. The built-in "sas.cli" also
# works (refresh_token and password grants, no registration needed).
VI_CLIENT_ID = _env("VI_CLIENT_ID", "CLIENT_ID", default="sas-mcp")
VI_CLIENT_SECRET = _env("VI_CLIENT_SECRET", "CLIENT_SECRET")

# Preferred credential: a refresh token obtained once with
# `vi-get-refresh-token` (browser sign-in, works for SSO/federated identities
# and needs no stored password). Takes precedence over username/password.
VI_REFRESH_TOKEN = _env("VI_REFRESH_TOKEN", "VIYA_REFRESH_TOKEN")

# Fallback credential: the password grant, only for accounts SAS Logon
# authenticates directly (local/LDAP users on a RACE image) and only with a
# client that allows it (set VI_CLIENT_ID=sas.cli; sas-mcp does not).
VI_USERNAME = _env("VI_USERNAME", "VIYA_USERNAME")
VI_PASSWORD = _env("VI_PASSWORD", "VIYA_PASSWORD")

# RACE/Engage images and quick tunnels use self-signed / re-terminated TLS.
VI_SSL_VERIFY = _bool("VI_SSL_VERIFY", True, "SSL_VERIFY")
VI_TIMEOUT = float(_int("VI_TIMEOUT", 120))

# --- Service base paths (relative to VI_ENDPOINT) ---------------------------
# These match a standard Visual Investigator deployment; override only if the
# ingress rewrites paths. The workflow service is mounted under svi-datahub.
VI_ALERT_BASE = os.getenv("VI_ALERT_BASE", "/svi-alert")
VI_DATAHUB_BASE = os.getenv("VI_DATAHUB_BASE", "/svi-datahub")
VI_SAND_BASE = os.getenv("VI_SAND_BASE", "/svi-sand")
VI_WORKFLOW_BASE = os.getenv("VI_WORKFLOW_BASE", "/svi-datahub/workflows")

SERVICE_BASES = {
    "alert": VI_ALERT_BASE,
    "datahub": VI_DATAHUB_BASE,
    "sand": VI_SAND_BASE,
    "workflows": VI_WORKFLOW_BASE,
}

# --- Behaviour --------------------------------------------------------------
# Write actions (dispositions, alert actions, workflow completion, generic
# POST/PUT) are disabled unless explicitly enabled, so a read-only demo agent
# can never mutate the investigation environment by accident.
VI_ALLOW_ACTIONS = _bool("VI_ALLOW_ACTIONS", False)

# Free-text description of what this VI deployment contains, surfaced to the
# agent through get_investigation_scope so it can explain its own scope.
VI_USE_CASE = os.getenv(
    "VI_USE_CASE",
    "Procurement integrity monitoring: alerts on suppliers, tenders and "
    "payments flagged by detection scenarios, with entity networks and "
    "workflows for investigation.",
)

# Cap on any single tool response, so one verbose VI payload cannot blow up
# the agent's context window.
VI_MAX_CHARS = _int("VI_MAX_CHARS", 16000)

# --- Serving ----------------------------------------------------------------
HOST_PORT = _int("HOST_PORT", 8141)
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "http").lower()
# Optional static key protecting the /mcp endpoint (X-API-Key or Bearer).
MCP_API_KEY = os.getenv("MCP_API_KEY", "")


def auth_mode() -> str:
    """Which SAS Logon grant the server will use: ``refresh_token``,
    ``password`` or ``none`` (no usable credentials configured)."""
    if VI_REFRESH_TOKEN:
        return "refresh_token"
    if VI_USERNAME and VI_PASSWORD:
        return "password"
    return "none"


def configured() -> bool:
    """True when there is enough configuration to attempt a connection."""
    return bool(VI_ENDPOINT) and auth_mode() != "none"
