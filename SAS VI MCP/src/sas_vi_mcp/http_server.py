#!/usr/bin/env python3
"""HTTP MCP server for SAS Visual Investigator.

Serves the MCP protocol over streamable HTTP at /mcp so it can be hosted as a
Container MCP Server in SAS Retrieval Agent Manager (RAM). The server signs in
to VI itself (SAS Logon), so MCP clients perform no OAuth. The endpoint can
optionally be protected with a static key via ``MCP_API_KEY`` (sent as
``X-API-Key`` or ``Authorization: Bearer``); ``/health`` stays open for
liveness probes.
"""

import hmac

import uvicorn
from fastmcp import FastMCP
from starlette.responses import JSONResponse

from . import config
from .config import logger
from .tools import register_tools

mcp = FastMCP("SAS Visual Investigator MCP Server")
register_tools(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    return JSONResponse({
        "status": "healthy",
        "service": "sas-vi-mcp",
        "vi_endpoint_configured": bool(config.VI_ENDPOINT),
        "credentials_configured": config.configured(),
        "auth_mode": config.auth_mode(),
        "client_id": config.VI_CLIENT_ID,
        "write_actions_enabled": config.VI_ALLOW_ACTIONS,
    })


class ApiKeyMiddleware:
    """ASGI middleware that rejects HTTP requests lacking the API key."""

    def __init__(self, app, api_key: str):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode(errors="ignore")
                   for k, v in scope.get("headers", [])}
        provided = headers.get("x-api-key", "")
        if not provided:
            parts = headers.get("authorization", "").split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                provided = parts[1]
        if not hmac.compare_digest(provided, self.api_key):
            response = JSONResponse({"error": "invalid or missing API key"},
                                    status_code=401)
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


def build_app():
    if config.MCP_TRANSPORT not in ("http", "sse"):
        raise ValueError(
            f"MCP_TRANSPORT must be 'http' or 'sse', got "
            f"'{config.MCP_TRANSPORT}'")
    if not config.configured():
        logger.warning(
            "VI connection not fully configured — tools will return setup "
            "guidance until VI_ENDPOINT and credentials are set.")
    logger.info("Serving MCP over '%s' transport (endpoint: /%s)",
                config.MCP_TRANSPORT,
                "mcp" if config.MCP_TRANSPORT == "http" else "sse")
    app = mcp.http_app(transport=config.MCP_TRANSPORT)
    if config.MCP_API_KEY:
        logger.info("API key protection enabled (MCP_API_KEY is set)")
        return ApiKeyMiddleware(app, config.MCP_API_KEY)
    logger.warning("MCP_API_KEY is not set — the MCP endpoint is "
                   "unauthenticated (fine when RAM reaches it in-cluster).")
    return app


def main():
    uvicorn.run(build_app(), host="0.0.0.0", port=config.HOST_PORT)


if __name__ == "__main__":
    main()
