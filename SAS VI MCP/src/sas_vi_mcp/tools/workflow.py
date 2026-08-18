"""Investigation workflow tools — workflows v4 (mounted under svi-datahub).

Read tools list tasks and processes; completing a task is gated behind
VI_ALLOW_ACTIONS because it advances a real investigation.
"""


from fastmcp import FastMCP

from ..shaping import collection_items, shape_process, shape_task
from ..vi_client import compact, require_actions_enabled, vi_request

_WF_ACTION_CT = "application/vnd.sas.investigation.workflow.action+json"
# The workflow service varies responses by client; desktop matches the VI UI.
_WF_HEADERS = {"VI-Client-Application": "desktop"}


def register(mcp: FastMCP) -> None:

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_workflow_tasks(
        only_workable: bool = True,
        start: int = 0,
        limit: int = 25,
        filter: str | None = None,
    ) -> dict:
        """List investigation workflow tasks. only_workable=True returns just
        the tasks the signed-in service account is allowed to work — set it
        False to see every open task (e.g. for a workload overview)."""
        params: dict = {"start": start, "limit": limit}
        if only_workable:
            params["includeOnlyWorkableTasks"] = "true"
        if filter:
            params["filter"] = filter
        data = await vi_request("GET", "workflows", "/processes/tasks",
                                params=params, headers=_WF_HEADERS)
        items, count = collection_items(data)
        return compact({
            "count": count if count is not None else len(items),
            "tasks": [shape_task(t) for t in items],
        })

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_workflow_task(task_id: str) -> dict:
        """Get one workflow task in full, including the actions available to
        complete it — call this before complete_workflow_task to see the
        valid action names."""
        data = await vi_request(
            "GET", "workflows", f"/processes/tasks/tasks/{task_id}",
            headers=_WF_HEADERS)
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_workflow_processes(
        active_only: bool = True, start: int = 0, limit: int = 25
    ) -> dict:
        """List investigation workflow processes (one per entity under
        investigation), active ones by default."""
        path = "/processes/actives" if active_only else "/processes"
        data = await vi_request("GET", "workflows", path,
                                params={"start": start, "limit": limit},
                                headers=_WF_HEADERS)
        items, count = collection_items(data)
        return compact({
            "count": count if count is not None else len(items),
            "processes": [shape_process(p) for p in items],
        })

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    async def complete_workflow_task(
        task_id: str,
        action_name: str,
        action_id: str | None = None,
    ) -> dict:
        """Complete a workflow task with one of its available actions (get
        the valid names/ids from get_workflow_task first). This advances a
        real investigation — requires VI_ALLOW_ACTIONS=true and explicit
        user confirmation."""
        require_actions_enabled("complete_workflow_task")
        body: dict = {"name": action_name}
        if action_id:
            body["id"] = action_id
        data = await vi_request(
            "PUT", "workflows",
            f"/processes/tasks/tasks/{task_id}/completed",
            body=body, content_type=_WF_ACTION_CT, headers=_WF_HEADERS)
        return compact({"taskId": task_id, "action": action_name,
                        "result": data})
