import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import RateLimitError

from fraud_service.app import create_app
from fraud_service.config import Settings
from fraud_service.models import Investigation


def test_discovery_and_filtering(client):
    assert client.get("/health").json()["mode"] == "demo"
    assert client.get("/docs").status_code == 200
    assert len(client.get("/demo/cases").json()) == 4
    flagged = client.get("/transactions?flagged_only=true").json()
    assert all(item["detection"]["flagged"] for item in flagged)
    assert {item["transaction"]["transaction_id"] for item in flagged if item["demo_label"]} == {
        "txn_spike",
        "txn_velocity",
        "txn_business",
    }
    assert client.get("/transactions?limit=0").status_code == 422


@pytest.mark.parametrize(
    "tx_id,score,assessment_risk",
    [
        ("txn_normal", 0, "low"),
        ("txn_spike", 100, "high"),
        ("txn_velocity", 30, "medium"),
        ("txn_business", 30, "low"),
    ],
)
def test_end_to_end_investigation_uses_real_stdio_mcp(client, tx_id, score, assessment_risk):
    response = client.post(f"/investigate/{tx_id}")
    assert response.status_code == 200, response.text
    result = Investigation.model_validate(response.json())
    assert result.mode == "demo"
    assert result.model is None
    assert result.detection.risk_score == score
    assert result.assessment.risk_level == assessment_risk
    assert [t.tool for t in result.tool_trace] == [
        "get_transaction_details",
        "get_account_history",
        "get_fraud_rules",
    ]
    assert result.tool_trace[0].result["transaction_id"] == tx_id
    assert "no LLM" in result.assessment.limitations[0]
    saved = client.get(f"/investigations/{result.investigation_id}")
    assert saved.json() == response.json()


@pytest.mark.parametrize(
    "path,method",
    [
        ("/investigate/unknown", "post"),
        ("/transactions/unknown", "get"),
        ("/accounts/unknown/history", "get"),
        ("/investigations/unknown", "get"),
    ],
)
def test_unknown_resource_is_404(client, path, method):
    assert getattr(client, method)(path).status_code == 404


def test_live_mode_requires_key_without_silent_fallback(tmp_path):
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "live.db",
        investigation_mode="groq",
        groq_api_key="",
    )
    with TestClient(create_app(settings)) as client:
        assert client.post("/investigate/txn_spike").status_code == 503


def test_deadline_returns_504(client, monkeypatch):
    async def slow(*args):
        await asyncio.sleep(1)

    monkeypatch.setattr("fraud_service.app.investigate", slow)
    client.app.state.settings.investigation_timeout_seconds = 0.01
    assert client.post("/investigate/txn_spike").status_code == 504


def test_provider_error_returns_sanitized_502(client, monkeypatch):
    async def fail(*args):
        raise RuntimeError("secret-provider-detail")

    monkeypatch.setattr("fraud_service.app.investigate", fail)
    response = client.post("/investigate/txn_spike")
    assert response.status_code == 502
    assert "secret-provider-detail" not in response.text


def test_timeout_cleans_up_real_mcp_session(client, monkeypatch):
    async def slow(bridge):
        await bridge.call("get_fraud_rules", {})
        await asyncio.sleep(10)

    monkeypatch.setattr("fraud_service.investigator.demo_assessment", slow)
    client.app.state.settings.investigation_timeout_seconds = 2
    assert client.post("/investigate/txn_spike").status_code == 504


@pytest.mark.parametrize("wrapped", [False, True])
def test_groq_rate_limit_returns_actionable_429(client, monkeypatch, wrapped):
    async def fail(*args):
        error = RateLimitError(
            "provider details",
            response=httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com")),
            body=None,
        )
        if wrapped:
            raise ExceptionGroup("MCP context", [error])
        raise error

    monkeypatch.setattr("fraud_service.app.investigate", fail)
    response = client.post("/investigate/txn_spike")
    assert response.status_code == 429
    assert "Groq usage limit" in response.json()["detail"]
    assert "provider details" not in response.text


def test_http_mcp_discovery_and_tool_call(client):
    headers = {"Accept": "application/json, text/event-stream", "Host": "127.0.0.1:8000"}

    def rpc(method, params=None, call_id=1):
        return client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": call_id,
                "method": method,
                "params": params or {},
            },
        )

    initialized = rpc(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )
    assert initialized.status_code == 200, initialized.text
    listed = rpc("tools/list").json()["result"]["tools"]
    assert {tool["name"] for tool in listed} == {
        "get_transaction_details",
        "get_account_history",
        "get_fraud_rules",
    }
    called = rpc(
        "tools/call",
        {"name": "get_transaction_details", "arguments": {"transaction_id": "txn_spike"}},
    )
    assert called.status_code == 200
    assert called.json()["result"]["structuredContent"]["amount_cents"] == 920000
    missing = rpc(
        "tools/call",
        {"name": "get_transaction_details", "arguments": {"transaction_id": "unknown"}},
    )
    assert missing.json()["result"]["isError"] is True


def test_database_seeding_is_idempotent(repository):
    count = len(repository.transactions())
    repository.initialize()
    assert len(repository.transactions()) == count == 32
