"""Alert triage tools — svi-alert v6.

Read tools cover the full triage loop (queue -> alert -> evidence -> score);
the two write tools (disposition, alert action) are gated behind
VI_ALLOW_ACTIONS.
"""


from fastmcp import FastMCP

from ..shaping import collection_items, shape_alert, shape_fired_event
from ..vi_client import compact, require_actions_enabled, vi_request

_TRIAGE_ACTION_CT = "application/vnd.sas.investigation.triage.action.request+json"


def register(mcp: FastMCP) -> None:

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_alerts(
        start: int = 0,
        limit: int = 25,
        sort_by: str = "score:descending",
        filter: str | None = None,
    ) -> dict:
        """List alerts in the Visual Investigator triage queue, highest score
        first by default. Returns compact records (id, label, score, status,
        queue, flagged entity). Use `filter` with SAS REST filter syntax to
        narrow, e.g. contains(label,'ACME') or eq(status,'OPEN'); use
        sort_by='' if the deployment rejects the score sort."""
        params: dict = {"start": start, "limit": limit}
        if sort_by:
            params["sortBy"] = sort_by
        if filter:
            params["filter"] = filter
        data = await vi_request("GET", "alert", "/alerts", params=params)
        items, count = collection_items(data)
        return compact({
            "count": count if count is not None else len(items),
            "returned": len(items),
            "alerts": [shape_alert(a) for a in items],
        })

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_alert(alert_id: str) -> dict:
        """Get the full record of one alert by ID: scores, status, queue and
        routing, the flagged entity, and disposition/workflow state."""
        data = await vi_request("GET", "alert", f"/alerts/{alert_id}")
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_alert_fired_events(
        alert_id: str, start: int = 0, limit: int = 25
    ) -> dict:
        """Get the scenario-fired events behind one alert — the specific
        detections that raised it and their evidence values. Essential for
        explaining WHY an alert fired and judging false positives."""
        data = await vi_request(
            "GET", "alert", f"/alerts/{alert_id}/scenarioFiredEvents",
            params={"start": start, "limit": limit})
        items, count = collection_items(data)
        return compact({
            "alertId": alert_id,
            "count": count if count is not None else len(items),
            "firedEvents": [shape_fired_event(e) for e in items],
        })

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_alert_scorecard(alert_id: str) -> dict:
        """Get the scorecard for one alert: how each contributing scenario's
        score rolls up into the alert's total. Use to explain the score
        composition to an investigator."""
        data = await vi_request(
            "GET", "alert", f"/alerts/{alert_id}/scorecard",
            params={"includeScenarioFiredEventLabels": "true"})
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_alert_queues(start: int = 0, limit: int = 50) -> dict:
        """List the alert queues (work baskets) configured in Visual
        Investigator, e.g. to say where an alert can be routed."""
        data = await vi_request("GET", "alert", "/queues",
                                params={"start": start, "limit": limit})
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_alert_strategies(start: int = 0, limit: int = 50) -> dict:
        """List the alerting strategies (how scenario events are grouped into
        alerts per entity type). Useful for understanding the detection
        setup behind the triage queue."""
        data = await vi_request("GET", "alert", "/strategies",
                                params={"start": start, "limit": limit})
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_alert_dispositions(alert_id: str | None = None) -> dict:
        """List the dispositions (close/suppress/escalate decisions) that are
        configured. Pass alert_id to see only the dispositions valid for
        that alert — do this before disposition_alert."""
        path = (f"/alerts/{alert_id}/alertDispositions"
                if alert_id else "/alertDispositions")
        data = await vi_request("GET", "alert", path)
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    async def disposition_alert(
        alert_id: str,
        disposition_id: str,
        queue_id: str | None = None,
    ) -> dict:
        """Apply a disposition to one alert (e.g. close as false positive,
        escalate to a case). Requires VI_ALLOW_ACTIONS=true on the server.
        Get valid disposition IDs from list_alert_dispositions(alert_id)
        first, and only act after the user has explicitly confirmed."""
        require_actions_enabled("disposition_alert")
        body: dict = {"dispositionId": disposition_id}
        if queue_id:
            body["queueId"] = queue_id
        data = await vi_request(
            "POST", "alert",
            f"/alerts/{alert_id}/alertDecisions/{disposition_id}",
            body=body, content_type=_TRIAGE_ACTION_CT)
        return compact({"alertId": alert_id, "dispositionId": disposition_id,
                        "result": data})

    @mcp.tool(annotations={"readOnlyHint": False})
    async def perform_alert_action(
        alert_id: str,
        action_type: str,
        user: str | None = None,
    ) -> dict:
        """Perform a triage action on one alert. action_type is one of
        CHECKOUT (claim it), CHECKIN (release it), ASSIGNMENT (assign to
        `user`), REACTIVATE. Requires VI_ALLOW_ACTIONS=true and explicit
        user confirmation."""
        require_actions_enabled("perform_alert_action")
        action_type = action_type.upper()
        valid = ("CHECKOUT", "CHECKIN", "ASSIGNMENT", "REACTIVATE")
        if action_type not in valid:
            return {"error": f"action_type must be one of {', '.join(valid)}"}
        body: dict = {"alertId": alert_id, "actionType": action_type}
        if user:
            body["user"] = user
        data = await vi_request(
            "POST", "alert", f"/alerts/{alert_id}/alertActions/{action_type}",
            body=body, content_type=_TRIAGE_ACTION_CT)
        return compact({"alertId": alert_id, "action": action_type,
                        "result": data})
