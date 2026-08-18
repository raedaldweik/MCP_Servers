"""Free-text search — svi-sand v10 (Search and Discovery).

Wraps POST /searches with a lucene text query and a summary visualization,
which is the shape the VI UI itself uses for its search bar.
"""


from fastmcp import FastMCP

from ..shaping import shape_search_hit
from ..vi_client import compact, vi_request

_SEARCH_CT = "application/vnd.sas.sand.search.request+json"


def register(mcp: FastMCP) -> None:

    @mcp.tool(annotations={"readOnlyHint": True})
    async def search_investigator(
        query: str,
        entity_types: list[str] | None = None,
        limit: int = 25,
    ) -> dict:
        """Free-text search across everything indexed in Visual Investigator
        (suppliers, tenders, payments, persons, ...). Supports lucene syntax
        (e.g. 'ACME', 'name:acme~ AND country:AE'). Use this to find an
        entity before pulling its details, or to sweep for a keyword across
        the whole investigation dataset. Restrict with entity_types (exact
        names from list_entity_types) when you know what you're looking
        for."""
        body: dict = {
            "query": {"type": "text", "language": "lucene", "text": query},
            "visualizations": {
                "hits": {"type": "hits"},
                "results": {
                    "type": "summary",
                    "start": 1,
                    "limit": max(1, min(limit, 200)),
                    "order": {"type": "score", "direction": "descending"},
                },
            },
        }
        if entity_types:
            body["types"] = entity_types

        data = await vi_request("POST", "sand", "/searches", body=body,
                                content_type=_SEARCH_CT)

        # Response mirrors the request keys under 'visualizations'.
        viz = data.get("visualizations", data) if isinstance(data, dict) else {}
        hits = viz.get("hits", {}) if isinstance(viz, dict) else {}
        results = viz.get("results", {}) if isinstance(viz, dict) else {}
        raw_items = []
        if isinstance(results, dict):
            for key in ("objects", "summaries", "items", "results", "hits"):
                if isinstance(results.get(key), list):
                    raw_items = results[key]
                    break
        if not raw_items and isinstance(data, dict) and isinstance(data.get("items"), list):
            raw_items = data["items"]

        shaped = [shape_search_hit(h) for h in raw_items if isinstance(h, dict)]
        out: dict = {"query": query, "returned": len(shaped),
                     "results": shaped}
        if isinstance(hits, dict):
            for key in ("count", "total", "value"):
                if hits.get(key) is not None:
                    out["totalHits"] = hits[key]
                    break
        if not shaped:
            # Don't hide an unexpected response shape from the agent.
            out["raw"] = data
        return compact(out)
