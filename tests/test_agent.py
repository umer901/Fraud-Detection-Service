import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI

from fraud_service.investigator import (
    GROQ_BASE_URL,
    InvestigationError,
    MCPBridge,
    connect_mcp,
    demo_assessment,
    live_assessment,
)


def tool_response(name, arguments, call_id):
    return SimpleNamespace(
        status="completed",
        output_parsed=None,
        output=[
            SimpleNamespace(
                type="function_call",
                name=name,
                arguments=json.dumps(arguments),
                call_id=call_id,
            )
        ],
    )


async def test_model_selects_tools_and_final_output_is_validated(settings, repository):
    tx = repository.transaction("txn_spike")
    async with connect_mcp(settings, tx) as bridge:
        expected = await demo_assessment(bridge)
    # Mock only the hosted model boundary. Tool discovery and execution use real MCP.
    client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=AsyncMock(
                side_effect=[
                    tool_response("get_fraud_rules", {}, "call_1"),
                    tool_response(
                        "get_transaction_details", {"transaction_id": tx.transaction_id}, "call_2"
                    ),
                    tool_response("get_account_history", {"account_id": tx.account_id}, "call_3"),
                    SimpleNamespace(status="completed", output=[], output_parsed=expected),
                ]
            )
        )
    )
    async with connect_mcp(settings, tx) as bridge:
        result = await live_assessment(bridge, settings, client)
        assert result == expected
        assert [t.tool for t in bridge.trace] == [
            "get_fraud_rules",
            "get_transaction_details",
            "get_account_history",
        ]
    calls = client.responses.parse.call_args_list
    assert calls[0].kwargs["tool_choice"] == "required"
    assert "tools" not in calls[-1].kwargs
    assert "text_format" not in calls[0].kwargs
    assert "text_format" in calls[-1].kwargs
    assert calls[-1].kwargs["store"] is False
    assert any(
        m.get("role") == "developer" for m in calls[-1].kwargs["input"] if isinstance(m, dict)
    )


async def test_out_of_scope_tool_requests_never_reach_mcp(repository):
    session = SimpleNamespace(call_tool=AsyncMock())
    bridge = MCPBridge(session, repository.transaction("txn_spike"), 12)
    with pytest.raises(InvestigationError, match="out-of-scope"):
        await bridge.call("get_account_history", {"account_id": "acc_alex"})
    with pytest.raises(InvestigationError, match="out-of-scope"):
        await bridge.call("delete_transaction", {"transaction_id": "txn_spike"})
    session.call_tool.assert_not_called()


async def test_tool_budget_stops_repeated_calls(settings, repository):
    tx = repository.transaction("txn_normal")
    async with connect_mcp(settings, tx) as bridge:
        bridge.max_calls = 1
        await bridge.call("get_fraud_rules", {})
        with pytest.raises(InvestigationError, match="tool-call budget"):
            await bridge.call("get_fraud_rules", {})


async def test_fabricated_evidence_is_rejected(settings, repository):
    async with connect_mcp(settings, repository.transaction("txn_normal")) as bridge:
        assessment = await demo_assessment(bridge)
        assessment.evidence[0].transaction_ids.append("invented_transaction")
        with pytest.raises(InvestigationError, match="unrelated evidence"):
            bridge.validate_assessment(assessment)


async def test_model_cannot_skip_required_evidence(settings, repository):
    client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=AsyncMock(
                return_value=SimpleNamespace(status="completed", output=[], output_parsed=None)
            )
        )
    )
    async with connect_mcp(settings, repository.transaction("txn_normal")) as bridge:
        with pytest.raises(InvestigationError, match="complete evidence"):
            await live_assessment(bridge, settings, client)


async def test_model_round_limit(settings, repository):
    client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=AsyncMock(return_value=tool_response("get_fraud_rules", {}, "repeat"))
        )
    )
    settings.max_agent_rounds = 2
    async with connect_mcp(settings, repository.transaction("txn_normal")) as bridge:
        with pytest.raises(InvestigationError, match="model-round budget"):
            await live_assessment(bridge, settings, client)


async def test_groq_sdk_serialization_and_parsing(settings, repository):
    tx = repository.transaction("txn_normal")
    async with connect_mcp(settings, tx) as bridge:
        assessment = await demo_assessment(bridge)
    requests = []
    calls = [
        ("get_transaction_details", {"transaction_id": tx.transaction_id}),
        ("get_account_history", {"account_id": tx.account_id}),
        ("get_fraud_rules", {}),
    ]

    def provider(request):
        assert str(request.url) == GROQ_BASE_URL + "/responses"
        body = json.loads(request.content)
        requests.append(body)
        index = len(requests) - 1
        if index < len(calls):
            name, arguments = calls[index]
            output = [
                {
                    "id": f"fc_{index}",
                    "type": "function_call",
                    "name": name,
                    "arguments": json.dumps(arguments),
                    "call_id": f"call_{index}",
                    "status": "completed",
                }
            ]
        else:
            output = [
                {
                    "id": "msg_final",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": assessment.model_dump_json(),
                            "annotations": [],
                        }
                    ],
                }
            ]
        return httpx.Response(
            200,
            json={
                "id": f"resp_{index}",
                "object": "response",
                "created_at": 1792324800,
                "status": "completed",
                "model": settings.groq_model,
                "output": output,
                "parallel_tool_calls": False,
                "tool_choice": body.get("tool_choice", "auto"),
                "tools": body.get("tools", []),
            },
        )

    async with AsyncOpenAI(
        api_key="test-only",
        base_url=GROQ_BASE_URL,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
    ) as api:
        async with connect_mcp(settings, tx) as bridge:
            result = await live_assessment(bridge, settings, api)
            assert result == assessment
            assert len(bridge.trace) == 3
    assert len(requests) == 4
    assert requests[-1]["text"]["format"]["type"] == "json_schema"
    assert requests[-1]["text"]["format"]["strict"] is True
    assert "tools" not in requests[-1]
    assert all("text" not in request for request in requests[:-1])
    assert len([m for m in requests[-1]["input"] if m.get("type") == "function_call_output"]) == 3
    rules_tool = next(t for t in requests[0]["tools"] if t["name"] == "get_fraud_rules")
    assert rules_tool["parameters"]["required"] == []
