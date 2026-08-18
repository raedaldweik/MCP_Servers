"""Scope and diagnostics tools."""

from fastmcp import FastMCP

from .. import config
from ..vi_client import VIError, vi_request


def register(mcp: FastMCP) -> None:

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_investigation_scope() -> dict:
        """Describe this assistant's investigation scope: what the connected
        SAS Visual Investigator environment contains, which capabilities are
        available, and whether write actions are enabled. Call this first in
        a new conversation to ground your answers."""
        return {
            "environment": config.VI_ENDPOINT or "(not configured)",
            "configured": config.configured(),
            "useCase": config.VI_USE_CASE,
            "writeActionsEnabled": config.VI_ALLOW_ACTIONS,
            "capabilities": {
                "alerts": "triage queue: list_alerts, get_alert, "
                          "get_alert_scorecard, get_alert_fired_events, "
                          "dispositions and alert actions",
                "entities": "data hub: list_entity_types, list_entities, "
                            "get_entity, get_related_entities, comments",
                "search": "free-text search across all indexed data: "
                          "search_investigator",
                "network": "link analysis: get_entity_network, "
                           "find_related_entities",
                "workflow": "investigation workflows: list_workflow_tasks, "
                            "get_workflow_task, processes",
            },
            "guidance": (
                "Typical triage flow: list_alerts (sorted by score) -> "
                "get_alert + get_alert_fired_events to see WHY it fired -> "
                "get_entity + get_entity_network on the flagged entity -> "
                "recommend a disposition."),
        }

    @mcp.tool(annotations={"readOnlyHint": True})
    async def check_vi_connection() -> dict:
        """Verify connectivity and authentication against the Visual
        Investigator environment. Use when another tool reports connection
        or sign-in problems, to tell configuration errors apart from data
        questions."""
        if not config.VI_ENDPOINT:
            return {"ok": False,
                    "problem": "VI_ENDPOINT is not set",
                    "fix": "Set VI_ENDPOINT in the RAM template environment "
                           "variables (the VI base URL or the current "
                           "cloudflared tunnel URL)."}
        checks = {}
        overall = True
        for service, path in (("alert", "/"), ("sand", "/")):
            try:
                await vi_request("GET", service, path)
                checks[service] = "ok"
            except VIError as exc:
                checks[service] = str(exc)[:200]
                overall = False
            except Exception as exc:  # auth errors included
                checks[service] = str(exc)[:200]
                overall = False
        return {"ok": overall, "endpoint": config.VI_ENDPOINT,
                "services": checks,
                "writeActionsEnabled": config.VI_ALLOW_ACTIONS}
