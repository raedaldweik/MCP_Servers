"""The full tool surface must register on a FastMCP instance and expose the
tools the RAM agent depends on, with descriptions."""

import pytest
from fastmcp import Client, FastMCP

from sas_vi_mcp.tools import register_tools

EXPECTED_TOOLS = {
    # scope / diagnostics
    "get_investigation_scope",
    "check_vi_connection",
    # alerts
    "list_alerts",
    "get_alert",
    "get_alert_fired_events",
    "get_alert_scorecard",
    "list_alert_queues",
    "list_alert_strategies",
    "list_alert_dispositions",
    "disposition_alert",
    "perform_alert_action",
    # entities
    "list_entity_types",
    "list_relationship_types",
    "list_entities",
    "get_entity",
    "get_related_entities",
    "get_entity_comments",
    "get_entity_attachments",
    "vi_api_request",
    # search + network
    "search_investigator",
    "get_entity_network",
    "find_related_entities",
    # workflow
    "list_workflow_tasks",
    "get_workflow_task",
    "list_workflow_processes",
    "complete_workflow_task",
}


@pytest.fixture()
async def tools():
    mcp = FastMCP("test")
    register_tools(mcp)
    async with Client(mcp) as client:
        return {t.name: t for t in await client.list_tools()}


async def test_all_expected_tools_registered(tools):
    assert EXPECTED_TOOLS <= set(tools)


async def test_every_tool_has_a_description(tools):
    for name in EXPECTED_TOOLS:
        assert tools[name].description, f"{name} is missing a description"


async def test_write_tools_error_when_actions_disabled(monkeypatch):
    from sas_vi_mcp import config
    monkeypatch.setattr(config, "VI_ALLOW_ACTIONS", False)
    mcp = FastMCP("test")
    register_tools(mcp)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "disposition_alert",
            {"alert_id": "A1", "disposition_id": "D1"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "VI_ALLOW_ACTIONS" in str(result.content)
