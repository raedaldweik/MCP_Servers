"""Configuration for the SAS Visual Investigator MCP server.

Everything is driven by environment variables so the container can be
configured entirely from the RAM template's Environment Variables tab
(the same convention as the SAS Viya MCP: endpoint + client + credentials,
with SSL verification switchable for tunnelled/RACE environments).
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


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("false", "0", "no", "off")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        logger.warning("Invalid integer for %s — using default %s", name, default)
        return default


# --- Connection -------------------------------------------------------------
# The base URL of the Visual Investigator environment. When VI runs on a RACE
# image that RAM cannot reach directly, this is the cloudflared tunnel URL
# (e.g. https://<random>.trycloudflare.com) started with:
#   cloudflared tunnel --url https://<race-host> --no-tls-verify \
#       --http-host-header <race-host>
VI_ENDPOINT = os.getenv("VI_ENDPOINT", "").rstrip("/")

# OAuth client used against {VI_ENDPOINT}/SASLogon/oauth/token.
# "sas.cli" exists out of the box on Viya and supports the password grant,
# which is the usual choice for RACE demo images. Use a registered client and
# refresh token for SSO/federated identities.
VI_CLIENT_ID = os.getenv("VI_CLIENT_ID", "sas.cli")
VI_CLIENT_SECRET = os.getenv("VI_CLIENT_SECRET", "")
VI_REFRESH_TOKEN = os.getenv("VI_REFRESH_TOKEN", "")
VI_USERNAME = os.getenv("VI_USERNAME", "")
VI_PASSWORD = os.getenv("VI_PASSWORD", "")

# RACE images and quick tunnels use self-signed / re-terminated TLS.
VI_SSL_VERIFY = _bool("VI_SSL_VERIFY", True)
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


def configured() -> bool:
    """True when there is enough configuration to attempt a connection."""
    return bool(VI_ENDPOINT) and bool(
        VI_REFRESH_TOKEN or (VI_USERNAME and VI_PASSWORD)
    )
