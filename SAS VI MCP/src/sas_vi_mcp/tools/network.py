"""Link analysis tools — svi-sand v10 (Network).

get_entity_network expands the graph around one entity (the VI network
canvas's expand operation); find_related_entities walks multi-hop paths from
an entity towards a target type (e.g. supplier -> shared directors ->
other suppliers).
"""


from fastmcp import FastMCP

from ..shaping import shape_graph
from ..vi_client import compact, vi_request

_GRAPH_CT = "application/vnd.sas.sand.graph.request+json"
_RELATED_CT = "application/vnd.sas.sand.related.objects.request+json"


def register(mcp: FastMCP) -> None:

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_entity_network(
        entity_type: str,
        entity_id: str,
        expansion_limit: int = 25,
    ) -> dict:
        """Get the relationship network around one entity — who/what it is
        directly linked to (the VI link-analysis canvas as data). Returns
        vertices and edges you can narrate or hand to a visualisation.
        expansion_limit caps neighbours per vertex to keep output focused."""
        body = {
            "query": {
                "type": "object",
                "objectIds": [{"type": entity_type, "id": entity_id}],
            },
        }
        data = await vi_request(
            "POST", "sand", "/graphs", body=body, content_type=_GRAPH_CT,
            params={"expansionLimit": max(1, min(expansion_limit, 100)),
                    "calculateMetrics": "false"})
        shaped = shape_graph(data if isinstance(data, dict) else {})
        shaped["seed"] = {"type": entity_type, "id": entity_id}
        if not shaped.get("vertexCount") and isinstance(data, dict):
            shaped["raw"] = data
        return compact(shaped)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def find_related_entities(
        start_type: str,
        start_id: str,
        end_types: list[str] | None = None,
        hops: int = 2,
        limit: int = 20,
    ) -> dict:
        """Find entities connected to a start entity within N relationship
        hops, optionally restricted to target types — e.g. from a flagged
        supplier, find other suppliers reachable via shared directors or
        addresses within 2 hops. This is the go-to tool for 'who else is
        connected?' questions."""
        body: dict = {
            "startQuery": {
                "type": "object",
                "objectIds": [{"type": start_type, "id": start_id}],
            },
            "hops": max(1, min(hops, 4)),
        }
        if end_types:
            body["endTypes"] = end_types
        data = await vi_request(
            "POST", "sand", "/relatedObjects", body=body,
            content_type=_RELATED_CT,
            params={"start": 0, "limit": max(1, min(limit, 100))})
        return compact({
            "start": {"type": start_type, "id": start_id},
            "hops": body["hops"],
            "related": data,
        })
