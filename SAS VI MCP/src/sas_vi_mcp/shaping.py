"""Shapers that trim verbose VI payloads down to what an investigator agent
actually needs. Every shaper is total: unknown/missing fields are simply
dropped, and an unrecognized record shape falls back to the raw item so no
data is ever hidden by mistake.
"""

from __future__ import annotations

from typing import Any


def _pick(record: dict, *names: str) -> Any:
    for name in names:
        value = record.get(name)
        if value is not None:
            return value
    return None


def collection_items(data: Any) -> tuple[list, int | None]:
    """Extract (items, count) from a SAS collection response, tolerating both
    ``{items: [...], count: n}`` envelopes and bare lists."""
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            count = data.get("count")
            return items, count if isinstance(count, int) else None
        return [data], None
    if isinstance(data, list):
        return data, len(data)
    return [], None


def shape_alert(a: dict) -> dict:
    shaped = {
        "id": _pick(a, "id", "alertId"),
        "label": _pick(a, "label", "name", "displayName", "title"),
        "score": _pick(a, "score", "totalScore", "alertScore"),
        "status": _pick(a, "status", "state", "dispositionStatus"),
        "queue": _pick(a, "queueName", "queue", "queueId"),
        "strategy": _pick(a, "strategyName", "strategyId"),
        "domain": _pick(a, "domainName", "domainId"),
        "entityType": _pick(a, "entityType", "objectTypeName", "documentType"),
        "entityId": _pick(a, "entityId", "objectId", "documentId"),
        "entityLabel": _pick(a, "entityLabel", "objectLabel"),
        "assignedTo": _pick(a, "assignedTo", "owner", "assignee", "checkedOutBy"),
        "createdAt": _pick(a, "createdTimeStamp", "createdTimestamp", "creationTimeStamp"),
        "modifiedAt": _pick(a, "modifiedTimeStamp", "modifiedTimestamp"),
    }
    shaped = {k: v for k, v in shaped.items() if v is not None}
    # Scenario/reason info is the heart of triage — keep whichever key exists.
    for key in ("scenarios", "scenarioNames", "reasons", "contributingScenarios"):
        if a.get(key) is not None:
            shaped[key] = a[key]
            break
    return shaped or a


def shape_fired_event(e: dict) -> dict:
    shaped = {
        "id": _pick(e, "id", "sfeId", "scenarioFiredEventId"),
        "scenario": _pick(e, "scenarioName", "scenarioLabel", "scenarioId"),
        "score": _pick(e, "score", "eventScore", "contribution"),
        "message": _pick(e, "message", "description", "label"),
        "disposition": _pick(e, "disposition", "dispositionName", "dispositionId"),
        "firedAt": _pick(e, "createdTimeStamp", "creationTimeStamp", "firedTimestamp"),
        "entityType": _pick(e, "entityType", "objectTypeName"),
        "entityId": _pick(e, "entityId", "objectId"),
    }
    # Keep the actual detection values — that's the evidence.
    for key in ("outputValues", "values", "eventValues", "attributes"):
        if e.get(key) is not None:
            shaped[key] = e[key]
            break
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or e


def shape_entity_type(t: dict) -> dict:
    shaped = {
        "name": _pick(t, "name", "typeName"),
        "label": _pick(t, "label", "displayName"),
        "description": _pick(t, "description"),
        "kind": _pick(t, "storedObjectType", "type", "kind"),
    }
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or t


def shape_relationship_type(r: dict) -> dict:
    shaped = {
        "name": _pick(r, "name", "relationshipTypeName"),
        "label": _pick(r, "label", "displayName"),
        "from": _pick(r, "fromEntityTypeName", "sourceTypeName", "fromObjectTypeName"),
        "to": _pick(r, "toEntityTypeName", "targetTypeName", "toObjectTypeName"),
        "description": _pick(r, "description"),
    }
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or r


def shape_search_hit(hit: dict) -> dict:
    shaped = {
        "type": _pick(hit, "type", "objectTypeName"),
        "id": _pick(hit, "id", "objectId"),
        "label": _pick(hit, "label", "displayLabel", "title"),
        "score": _pick(hit, "score", "relevance"),
    }
    for key in ("fields", "summary", "highlights", "values"):
        if hit.get(key) is not None:
            shaped[key] = hit[key]
            break
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or hit


def shape_graph(data: dict) -> dict:
    """Reduce a svi-sand graph response to vertices/edges lists an agent can
    narrate ('supplier X links to person Y via director-of')."""
    if not isinstance(data, dict):
        return {"raw": data}
    vertices = data.get("vertices") or data.get("nodes") or []
    edges = data.get("edges") or data.get("links") or []
    shaped_vertices = []
    for v in vertices if isinstance(vertices, list) else []:
        shaped_vertices.append({k: v.get(src) for k, src in (
            ("type", "type"), ("id", "id"), ("label", "label"),
            ("degree", "degree")) if v.get(src) is not None} or v)
    shaped_edges = []
    for e in edges if isinstance(edges, list) else []:
        shaped_edges.append({k: e.get(src) for k, src in (
            ("type", "type"), ("id", "id"), ("label", "label"),
            ("from", "from"), ("to", "to"),
            ("source", "source"), ("target", "target")) if e.get(src) is not None} or e)
    return {
        "vertexCount": len(shaped_vertices),
        "edgeCount": len(shaped_edges),
        "vertices": shaped_vertices,
        "edges": shaped_edges,
    }


def shape_task(t: dict) -> dict:
    shaped = {
        "id": _pick(t, "id", "taskId"),
        "name": _pick(t, "name", "label", "taskName"),
        "state": _pick(t, "state", "status"),
        "assignee": _pick(t, "assignee", "claimedBy", "owner"),
        "processId": _pick(t, "processId", "workflowProcessId"),
        "workflow": _pick(t, "workflowName", "processDefinitionName"),
        "entityType": _pick(t, "entityName", "entityTypeName"),
        "entityInstanceId": _pick(t, "entityInstanceId"),
        "createdAt": _pick(t, "createdTimeStamp", "creationTimeStamp", "startTime"),
        "dueAt": _pick(t, "dueDate", "dueTimeStamp"),
    }
    if t.get("actions") is not None:
        shaped["actions"] = [
            {"id": a.get("id"), "name": a.get("name")}
            if isinstance(a, dict) else a
            for a in (t["actions"] if isinstance(t["actions"], list) else [])
        ]
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or t


def shape_process(p: dict) -> dict:
    shaped = {
        "id": _pick(p, "id", "processId"),
        "workflow": _pick(p, "workflowName", "processDefinitionName", "name"),
        "state": _pick(p, "state", "status"),
        "suspended": _pick(p, "suspended"),
        "entityType": _pick(p, "entityName", "entityTypeName"),
        "entityInstanceId": _pick(p, "entityInstanceId"),
        "startedAt": _pick(p, "startTime", "createdTimeStamp", "creationTimeStamp"),
        "endedAt": _pick(p, "endTime"),
    }
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or p
