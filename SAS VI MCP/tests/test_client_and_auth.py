"""Unit tests for URL building, payload compaction, action gating and grant
selection — no network required."""

import pytest

from sas_vi_mcp import config
from sas_vi_mcp.auth import select_grant
from sas_vi_mcp.vi_client import (
    VIError,
    compact,
    require_actions_enabled,
    service_url,
)


def test_service_url_alert(monkeypatch):
    monkeypatch.setattr(config, "VI_ENDPOINT", "https://vi.example.com")
    assert (service_url("alert", "/alerts")
            == "https://vi.example.com/svi-alert/alerts")


def test_service_url_workflows_under_datahub(monkeypatch):
    monkeypatch.setattr(config, "VI_ENDPOINT", "https://vi.example.com")
    assert (service_url("workflows", "processes/tasks")
            == "https://vi.example.com/svi-datahub/workflows/processes/tasks")


def test_service_url_unknown_service():
    with pytest.raises(VIError, match="Unknown VI service"):
        service_url("nope", "/x")


def test_compact_passthrough_small():
    value = {"a": 1}
    assert compact(value) is value


def test_compact_truncates_large(monkeypatch):
    monkeypatch.setattr(config, "VI_MAX_CHARS", 100)
    result = compact({"data": "x" * 500})
    assert result["truncated"] is True
    assert len(result["preview"]) == 100


def test_actions_gated_by_default(monkeypatch):
    monkeypatch.setattr(config, "VI_ALLOW_ACTIONS", False)
    with pytest.raises(VIError, match="VI_ALLOW_ACTIONS"):
        require_actions_enabled("disposition_alert")


def test_actions_allowed_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "VI_ALLOW_ACTIONS", True)
    require_actions_enabled("disposition_alert")  # must not raise


def test_select_grant_prefers_refresh_token():
    grant = select_grant(refresh_token="rt", username="u", password="p")
    assert grant == {"grant_type": "refresh_token", "refresh_token": "rt"}


def test_select_grant_password_fallback():
    grant = select_grant(username="u", password="p")
    assert grant["grant_type"] == "password"


def test_select_grant_none_without_credentials():
    assert select_grant() is None
