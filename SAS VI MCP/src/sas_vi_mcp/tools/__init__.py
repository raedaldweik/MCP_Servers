"""Tool registration for the SAS Visual Investigator MCP server."""

from fastmcp import FastMCP

from . import alerts, entities, network, scope, search, workflow


def register_tools(mcp: FastMCP) -> None:
    scope.register(mcp)
    alerts.register(mcp)
    entities.register(mcp)
    search.register(mcp)
    network.register(mcp)
    workflow.register(mcp)
