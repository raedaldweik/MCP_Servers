"""SAS Visual Investigator MCP server.

Exposes SAS Visual Investigator's REST services (svi-alert v6, svi-datahub
v11, svi-sand v10, workflows v4 — the 2026.04 API surface, pinned by the
OpenAPI specs in ``api-specs/``) as MCP tools for alert triage, entity
investigation, free-text search, network expansion and workflow handling.
"""

__version__ = "1.1.0"
