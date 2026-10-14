#!/usr/bin/env python3
"""(Admin, once per Viya deployment) Register the `sas-mcp` OAuth client on
the VI environment with a one-year refresh-token validity — the same client
definition as the SAS Viya MCP's examples/register_mcp_client.py. Not needed
when VI runs on the Viya where sas-mcp is already registered.

    uv run python examples/register_vi_client.py            # or: uv run vi-register-client
    uv run python examples/register_vi_client.py --insecure

Prompts for an admin account SAS Logon authenticates directly (e.g. sasboot),
or pass --admin-token / VI_ADMIN_TOKEN. See `vi-register-client --help`.
"""

import sys

from sas_vi_mcp.oauth_setup import register_client_main

if __name__ == "__main__":
    sys.exit(register_client_main())
