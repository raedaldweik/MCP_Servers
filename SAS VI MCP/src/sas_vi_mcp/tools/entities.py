"""Entity / data hub tools — svi-datahub v11.

Everything an agent needs to walk the data model: what entity types exist,
list and read records, follow relationships, and read investigator comments.
"""


from fastmcp import FastMCP

from ..shaping import (
    collection_items,
    shape_entity_type,
    shape_relationship_type,
)
from ..vi_client import compact, vi_request


def register(mcp: FastMCP) -> None:

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_entity_types() -> dict:
        """List the entity types defined in the Visual Investigator data hub
        (e.g. supplier, tender, payment, person). Call this before listing
        or reading entities so you use exact type names."""
        data = await vi_request(
            "GET", "datahub", "/admin/storedObjects/listAll",
            params={"excludeUnauthorized": "true"})
        items, _ = collection_items(data)
        return compact({
            "count": len(items),
            "entityTypes": [shape_entity_type(t) for t in items],
        })

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_relationship_types() -> dict:
        """List the relationship types defined between entity types (e.g.
        supplier -[has_director]-> person). Use the returned names with
        get_related_entities."""
        data = await vi_request("GET", "datahub", "/admin/relationships")
        items, _ = collection_items(data)
        return compact({
            "count": len(items),
            "relationshipTypes": [shape_relationship_type(r) for r in items],
        })

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_entities(
        entity_type: str, start: int = 0, limit: int = 25
    ) -> dict:
        """List records of one entity type from the data hub, with display
        labels. Use exact type names from list_entity_types."""
        data = await vi_request(
            "GET", "datahub", f"/documents/{entity_type}",
            params={"start": start, "limit": limit,
                    "includeDisplayLabel": "true"})
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_entity(
        entity_type: str, entity_id: str, include_children: bool = True
    ) -> dict:
        """Read one entity record in full (e.g. a supplier's complete
        profile). include_children also returns nested child documents."""
        data = await vi_request(
            "GET", "datahub", f"/documents/{entity_type}/{entity_id}",
            params={"depth": "max" if include_children else "0",
                    "includeDisplayLabel": "true"})
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_related_entities(
        entity_type: str,
        entity_id: str,
        relationship_type: str,
        start: int = 0,
        limit: int = 25,
    ) -> dict:
        """Follow one relationship type from an entity to its related records
        (e.g. supplier -> its payments). Get valid relationship names from
        list_relationship_types. For the whole neighbourhood at once use
        get_entity_network instead."""
        data = await vi_request(
            "GET", "datahub",
            f"/documents/{entity_type}/{entity_id}/{relationship_type}",
            params={"start": start, "limit": limit})
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_entity_comments(
        entity_type: str, entity_id: str, start: int = 0, limit: int = 25
    ) -> dict:
        """Read the investigator comments recorded on an entity — prior
        analyst findings and context that should inform any recommendation."""
        data = await vi_request(
            "GET", "datahub",
            f"/documents/{entity_type}/{entity_id}/comments",
            params={"start": start, "limit": limit})
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_entity_attachments(
        entity_type: str, entity_id: str
    ) -> dict:
        """List the file attachments on an entity (names and metadata only,
        not the file contents)."""
        data = await vi_request(
            "GET", "datahub",
            f"/documents/{entity_type}/{entity_id}/attachments")
        return compact(data)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def vi_api_request(
        method: str,
        service: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
    ) -> dict:
        """Generic Visual Investigator REST call — the exploration escape
        hatch when no dedicated tool covers an endpoint. `service` is one of
        alert, datahub, sand, workflows; `path` is relative to that service
        (e.g. service='alert', path='/alerts'). GET is always allowed; POST
        and PUT require VI_ALLOW_ACTIONS=true and are only for search-style
        or explicitly user-confirmed calls. Never guess destructive
        endpoints."""
        from ..vi_client import require_actions_enabled

        method = (method or "GET").upper()
        if method not in ("GET", "POST", "PUT"):
            return {"error": "method must be GET, POST, or PUT"}
        if method != "GET":
            require_actions_enabled(f"vi_api_request {method}")
        data = await vi_request(method, service, path, params=params,
                                body=body)
        return compact({"service": service, "path": path, "data": data})
