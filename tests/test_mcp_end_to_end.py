"""Call the tools through a real MCP client session, the same path Claude or ChatGPT uses."""

import pytest
from conftest import load
from mcp import Client

from cfp_scout.server import build_server

EXPECTED_TOOLS = {
    "search_calls",
    "get_call",
    "get_venue_rank",
    "verify_deadline",
    "watch_deadline",
    "check_watch",
    "stop_watch",
    "health_check",
}


async def test_every_tool_is_listed_with_typed_inputs_and_outputs(scout):
    async with Client(build_server(scout)) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.description, tool.name
        assert tool.input_schema["type"] == "object", tool.name
        assert tool.output_schema, tool.name


async def test_multi_step_conversation_flow(scout, gateway):
    gateway.pages["call?conference=robotics"] = load("category_robotics.html")
    gateway.pages["search=IROS"] = load("icore_iros.html")
    gateway.pages["eventid=204130"] = load("event_flairs.html")
    gateway.pages["example.org"] = "Important dates. Full papers due February 1, 2027."
    gateway.agent_answer = {
        "conference_name": "FLAIRS",
        "main_paper_deadline": "February 1, 2027",
        "deadline_quote": "Full papers due February 1, 2027",
        "evidence_url": "https://example.org/flairs-special-track/dates",
        "deadline_was_extended": False,
    }
    async with Client(build_server(scout)) as client:
        found = await client.call_tool("search_calls", {"topic": "robotics", "limit": 2})
        assert not found.is_error
        assert found.structured_content["calls"][0]["acronym"] == "AISRA 2026"

        rank = await client.call_tool("get_venue_rank", {"acronym": "IROS 2027"})
        assert rank.structured_content["is_ranked"] is True

        detail = await client.call_tool("get_call", {"event_id": 204130})
        assert detail.structured_content["official_url"] == "https://example.org/flairs-special-track/"

        checked = await client.call_tool("verify_deadline", {"event_id": 204130})
        assert checked.structured_content["status"] == "verified"
        assert checked.structured_content["matches_wikicfp"] is True


async def test_site_change_reaches_the_client_as_a_clear_error(scout, gateway):
    gateway.pages["call?conference=robotics"] = "<html><body>A new design</body></html>"
    async with Client(build_server(scout)) as client:
        result = await client.call_tool("search_calls", {"topic": "robotics"})
    assert result.is_error
    assert "SITE_CHANGED" in result.content[0].text
    assert "health_check" in result.content[0].text


@pytest.mark.parametrize(
    "tool, arguments",
    [
        ("get_call", {"event_id": 0}),
        ("search_calls", {"topic": "x", "limit": 999}),
        ("get_call", {"event_id": "not a number"}),
    ],
)
async def test_invalid_input_is_rejected_by_the_schema(scout, tool, arguments):
    async with Client(build_server(scout)) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error


async def test_missing_key_gives_setup_instructions(monkeypatch, tmp_path):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    monkeypatch.setenv("CFP_SCOUT_HOME", str(tmp_path))
    async with Client(build_server()) as client:
        tools = (await client.list_tools()).tools
        assert len(tools) == 8
        result = await client.call_tool("search_calls", {"topic": "robotics"})
    assert result.is_error
    assert "TINYFISH_API_KEY" in result.content[0].text
