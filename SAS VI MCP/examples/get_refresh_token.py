#!/usr/bin/env python3
"""Obtain the VI_REFRESH_TOKEN for a headless (RAM-hosted) deployment —
same recipe as the SAS Viya MCP's examples/get_refresh_token.py.

    uv run python examples/get_refresh_token.py            # or: uv run vi-get-refresh-token
    uv run python examples/get_refresh_token.py --insecure # RACE/Engage images, quick tunnels

Reads VI_ENDPOINT (or VIYA_ENDPOINT), VI_CLIENT_ID (or CLIENT_ID; default
sas-mcp, redirecting to http://localhost:8134/auth/callback exactly like the
SAS Viya MCP) and VI_SSL_VERIFY (or SSL_VERIFY) from .env. See
`vi-get-refresh-token --help` for all options.
"""

import sys

from sas_vi_mcp.oauth_setup import get_refresh_token_main

if __name__ == "__main__":
    sys.exit(get_refresh_token_main())
