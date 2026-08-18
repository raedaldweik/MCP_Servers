"""HTTP client for the Visual Investigator REST services.

One entry point, :func:`vi_request`, used by every tool. It signs the request
with a cached SAS Logon token (re-authenticating once on 401), targets a
service by name so tools never hard-code URLs, and returns either parsed JSON
or a :class:`VIError` with an actionable message — tools raise, the MCP layer
reports.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from . import config
from .auth import AuthenticationError, auth
from .config import logger


class VIError(RuntimeError):
    """A shaped, agent-actionable error from the VI REST surface."""


def service_url(service: str, path: str) -> str:
    try:
        base = config.SERVICE_BASES[service]
    except KeyError:
        raise VIError(
            f"Unknown VI service '{service}'. Valid services: "
            f"{', '.join(sorted(config.SERVICE_BASES))}.") from None
    if not path.startswith("/"):
        path = "/" + path
    return f"{config.VI_ENDPOINT}{base}{path}"


def _error_detail(resp: httpx.Response) -> str:
    """Pull the human-readable message out of a SAS error payload."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            parts = [str(body[k]) for k in ("message", "details", "error_description")
                     if body.get(k)]
            if parts:
                return "; ".join(parts)[:400]
    except Exception:
        pass
    return resp.text[:400]


def _hint_for_status(status: int, service: str, path: str) -> str:
    if status == 401:
        return ("Authentication was rejected even after refreshing the token. "
                "Verify the credentials and that the account is a VI user.")
    if status == 403:
        return ("The signed-in account lacks permission for this resource. "
                "Check its VI group/capability assignments.")
    if status == 404:
        return (f"'{path}' was not found on the {service} service. The record "
                "ID or type name may be wrong — list the available items "
                "first (e.g. list_entity_types, list_alerts).")
    if status == 400:
        return ("The request was malformed for this deployment — check "
                "filter/sortBy syntax and field names against the metadata "
                "tools before retrying.")
    if status >= 500:
        return ("The VI service errored internally. Retry once; if it "
                "persists, check the service's health in the environment.")
    return ""


def compact(value: Any, limit: int | None = None) -> Any:
    """Cap a JSON payload's serialized size so one verbose VI response can't
    blow up the agent's context. Returns the value unchanged when it fits."""
    limit = limit or config.VI_MAX_CHARS
    try:
        text = json.dumps(value, default=str)
    except Exception:
        return str(value)[:limit]
    if len(text) <= limit:
        return value
    return {
        "truncated": True,
        "note": (f"Response was {len(text)} characters; showing the first "
                 f"{limit}. Request fewer items (lower limit), a narrower "
                 "filter, or a specific record instead."),
        "preview": text[:limit],
    }


async def vi_request(
    method: str,
    service: str,
    path: str,
    *,
    params: dict | None = None,
    body: Any | None = None,
    content_type: str | None = None,
    headers: dict | None = None,
) -> Any:
    """Perform one authenticated request against a VI service.

    ``service`` is one of ``alert``, ``datahub``, ``sand``, ``workflows``.
    Returns parsed JSON (or raw text for non-JSON bodies). Raises
    :class:`VIError` / :class:`AuthenticationError` with actionable messages.
    """
    url = service_url(service, path)
    token = await auth.get_token()

    req_headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/json"}
    if content_type:
        req_headers["Content-Type"] = content_type
    if headers:
        req_headers.update(headers)

    async with httpx.AsyncClient(verify=config.VI_SSL_VERIFY,
                                 timeout=config.VI_TIMEOUT,
                                 follow_redirects=True) as client:
        try:
            resp = await client.request(
                method, url, params=params or None,
                json=body if body is not None else None,
                headers=req_headers)
            if resp.status_code == 401:
                # Token may have been revoked server-side — refresh once.
                auth.invalidate()
                token = await auth.get_token()
                req_headers["Authorization"] = f"Bearer {token}"
                resp = await client.request(
                    method, url, params=params or None,
                    json=body if body is not None else None,
                    headers=req_headers)
        except httpx.HTTPError as exc:
            raise VIError(
                f"Could not reach {url}: {exc}. If VI is behind a cloudflared "
                "quick tunnel, the tunnel may have restarted with a new URL — "
                "update VI_ENDPOINT to the current tunnel address.") from exc

    if resp.status_code >= 400:
        detail = _error_detail(resp)
        hint = _hint_for_status(resp.status_code, service, path)
        logger.warning("VI %s %s -> %s: %s", method, url, resp.status_code, detail)
        raise VIError(
            f"{method} {config.SERVICE_BASES[service]}{path} failed with "
            f"HTTP {resp.status_code}: {detail}" + (f" — {hint}" if hint else ""))

    if resp.status_code == 204 or not resp.content:
        return {"status": resp.status_code, "ok": True}
    try:
        return resp.json()
    except json.JSONDecodeError:
        return resp.text[: config.VI_MAX_CHARS]


def require_actions_enabled(action: str) -> None:
    """Guard for write tools: refuse unless VI_ALLOW_ACTIONS is set."""
    if not config.VI_ALLOW_ACTIONS:
        raise VIError(
            f"'{action}' modifies the investigation environment, and write "
            "actions are disabled on this server (VI_ALLOW_ACTIONS=false). "
            "Set VI_ALLOW_ACTIONS=true in the RAM template's environment "
            "variables to enable dispositions and workflow actions.")


__all__ = [
    "AuthenticationError",
    "VIError",
    "compact",
    "require_actions_enabled",
    "service_url",
    "vi_request",
]
