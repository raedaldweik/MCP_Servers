#!/usr/bin/env python3
"""stdio MCP server for SAS Visual Investigator — for local development and
desktop MCP clients (Claude Desktop, MCP Inspector). RAM uses the HTTP
server; both expose the identical tool set."""

from fastmcp import FastMCP

from .tools import register_tools

mcp = FastMCP("SAS Visual Investigator MCP Server")
register_tools(mcp)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
