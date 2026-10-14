"""SAS Logon (OAuth) token management for the Visual Investigator environment.

Grant preference:
1. ``refresh_token`` — works for any identity, including SSO/federated users.
2. ``password``      — for identities SAS Logon can authenticate directly
                       (LDAP-backed users, RACE demo accounts).

The token is cached and refreshed shortly before expiry; if SAS Logon rotates
the refresh token we keep the new one. Public clients differ by deployment:
some SAS Logon setups want ``client_id`` in the body with no Basic header,
others (e.g. ``sas.cli`` on RACE images) expect the empty-secret Basic form —
on a 401 we retry once with the other shape.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from . import config
from .config import logger

# Refresh the cached token this many seconds before it actually expires.
_TOKEN_EXPIRY_MARGIN = 60.0


class AuthenticationError(RuntimeError):
    pass


def select_grant(refresh_token: str = "", username: str = "",
                 password: str = "") -> dict | None:
    if refresh_token:
        return {"grant_type": "refresh_token", "refresh_token": refresh_token}
    if username and password:
        return {"grant_type": "password", "username": username, "password": password}
    return None


class SASLogonAuth:
    """Cached, lock-protected access-token provider for one VI environment."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._token = ""
        self._expires_at = 0.0
        # Seeded from config; updated if SAS Logon rotates it.
        self._refresh_token = config.VI_REFRESH_TOKEN

    async def get_token(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        async with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            return await self._fetch_token()

    async def _fetch_token(self) -> str:
        if not config.VI_ENDPOINT:
            raise AuthenticationError(
                "The Visual Investigator connection is not configured: "
                "VI_ENDPOINT is empty. Set VI_ENDPOINT (the VI base URL or "
                "its cloudflared tunnel URL) plus credentials "
                "(VI_REFRESH_TOKEN, or VI_USERNAME and VI_PASSWORD).")
        grant = select_grant(refresh_token=self._refresh_token,
                             username=config.VI_USERNAME,
                             password=config.VI_PASSWORD)
        if grant is None:
            raise AuthenticationError(
                "No Visual Investigator credentials configured. Set "
                "VI_REFRESH_TOKEN (obtain it once with `vi-get-refresh-token`; "
                "required for SSO/federated identities) or VI_USERNAME and "
                "VI_PASSWORD.")

        token_url = f"{config.VI_ENDPOINT}/SASLogon/oauth/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {**grant, "client_id": config.VI_CLIENT_ID}
        auth = ((config.VI_CLIENT_ID, config.VI_CLIENT_SECRET)
                if config.VI_CLIENT_SECRET else None)

        try:
            async with httpx.AsyncClient(verify=config.VI_SSL_VERIFY,
                                         timeout=60.0) as client:
                resp = await client.post(token_url, auth=auth, headers=headers,
                                         data=data)
                if resp.status_code == 401 and not config.VI_CLIENT_SECRET:
                    resp = await client.post(
                        token_url, auth=(config.VI_CLIENT_ID, ""),
                        headers=headers, data=grant)
        except httpx.HTTPError as exc:
            raise AuthenticationError(
                f"Could not reach SAS Logon at {token_url}: {exc}. If VI is "
                "behind a cloudflared quick tunnel, check the tunnel is still "
                "running and VI_ENDPOINT matches its current URL.") from exc

        if resp.status_code >= 400:
            if grant["grant_type"] == "refresh_token":
                hint = (
                    "The refresh token was rejected: it has expired or been "
                    f"revoked, or VI_CLIENT_ID ('{config.VI_CLIENT_ID}') is not "
                    "the client it was issued to. Run `vi-get-refresh-token` "
                    "again, update VI_REFRESH_TOKEN (and VI_CLIENT_ID) in the "
                    "RAM template's environment variables, and restart the tool.")
            else:
                hint = (
                    "Check VI_USERNAME, VI_PASSWORD and VI_CLIENT_ID. SSO/"
                    "federated accounts cannot use the password grant — use "
                    "VI_REFRESH_TOKEN from `vi-get-refresh-token` instead.")
            raise AuthenticationError(
                f"Visual Investigator sign-in failed ({resp.status_code}) using "
                f"the {grant['grant_type']} grant: {resp.text[:300]}. {hint}")

        body = resp.json()
        self._token = body["access_token"]
        expires_in = float(body.get("expires_in", 0))
        self._expires_at = time.monotonic() + max(
            expires_in - _TOKEN_EXPIRY_MARGIN, 0.0)
        if body.get("refresh_token"):
            self._refresh_token = body["refresh_token"]
        logger.info("Obtained VI access token (expires in %.0fs)", expires_in)
        return self._token

    def invalidate(self) -> None:
        """Drop the cached token so the next call re-authenticates."""
        self._token = ""
        self._expires_at = 0.0


auth = SASLogonAuth()
