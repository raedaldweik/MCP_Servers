"""Unit tests for the response shapers — no network required."""

from sas_vi_mcp.shaping import (
    collection_items,
    shape_alert,
    shape_entity_type,
    shape_fired_event,
    shape_graph,
    shape_process,
    shape_search_hit,
    shape_task,
)


def test_collection_items_envelope():
    items, count = collection_items({"items": [{"a": 1}], "count": 7})
    assert items == [{"a": 1}]
    assert count == 7


def test_collection_items_bare_list():
    items, count = collection_items([{"a": 1}, {"b": 2}])
    assert len(items) == 2
    assert count == 2


def test_collection_items_single_object():
    items, count = collection_items({"id": "x"})
    assert items == [{"id": "x"}]
    assert count is None


def test_shape_alert_picks_aliases():
    shaped = shape_alert({
        "alertId": "A1", "name": "Supplier ACME", "totalScore": 88,
        "state": "OPEN", "queueName": "Procurement",
        "objectTypeName": "supplier", "objectId": "S9",
        "scenarioNames": ["split-po"],
        "irrelevantInternalField": "x" * 500,
    })
    assert shaped["id"] == "A1"
    assert shaped["label"] == "Supplier ACME"
    assert shaped["score"] == 88
    assert shaped["status"] == "OPEN"
    assert shaped["entityType"] == "supplier"
    assert shaped["scenarioNames"] == ["split-po"]
    assert "irrelevantInternalField" not in shaped


def test_shape_alert_unrecognized_falls_back_to_raw():
    raw = {"weird": "shape"}
    assert shape_alert(raw) == raw


def test_shape_fired_event_keeps_evidence():
    shaped = shape_fired_event({
        "id": "E1", "scenarioName": "round-amounts", "score": 30,
        "outputValues": {"amount": 10000},
    })
    assert shaped["scenario"] == "round-amounts"
    assert shaped["outputValues"] == {"amount": 10000}


def test_shape_entity_type():
    shaped = shape_entity_type({"name": "supplier", "label": "Supplier"})
    assert shaped == {"name": "supplier", "label": "Supplier"}


def test_shape_search_hit():
    shaped = shape_search_hit({"type": "supplier", "id": "S1",
                               "label": "ACME", "score": 4.2,
                               "fields": {"country": "AE"}})
    assert shaped["type"] == "supplier"
    assert shaped["fields"] == {"country": "AE"}


def test_shape_graph_counts():
    shaped = shape_graph({
        "vertices": [{"type": "supplier", "id": "S1", "label": "ACME"},
                     {"type": "person", "id": "P1", "label": "J. Doe"}],
        "edges": [{"type": "director_of", "from": "P1", "to": "S1"}],
    })
    assert shaped["vertexCount"] == 2
    assert shaped["edgeCount"] == 1
    assert shaped["edges"][0]["type"] == "director_of"


def test_shape_graph_tolerates_non_dict():
    assert shape_graph("oops") == {"raw": "oops"}


def test_shape_task_actions():
    shaped = shape_task({"id": "T1", "name": "Review alert",
                         "actions": [{"id": "a1", "name": "Close",
                                      "extra": "dropped"}]})
    assert shaped["actions"] == [{"id": "a1", "name": "Close"}]


def test_shape_process():
    shaped = shape_process({"id": "P1", "workflowName": "Investigate",
                            "suspended": False})
    assert shaped["workflow"] == "Investigate"
    assert shaped["suspended"] is False
