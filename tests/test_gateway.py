import json

import httpx
import pytest

from cfp_scout.errors import AgentRunError, MissingApiKeyError, PageFetchError, TinyFishApiError
from cfp_scout.gateway import TinyFishGateway

KEY = "test-key-should-never-leak"


def gateway_with(handler, key=KEY):
    return TinyFishGateway(api_key=key, transport=httpx.MockTransport(handler), retry_delay=0)


async def test_fetch_sends_key_and_selector_and_reads_text():
    seen = {}

    def handler(request):
        seen["key"] = request.headers["X-API-Key"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [{"url": "u", "final_url": "f", "title": "t", "text": "<body/>"}], "errors": []})

    page = await gateway_with(handler).fetch_page("http://www.wikicfp.com/x", ttl=60)
    assert page.text == "<body/>" and page.title == "t"
    assert seen["key"] == KEY
    assert seen["url"].rstrip("/") == "https://api.fetch.tinyfish.ai"
    assert seen["body"]["include_selectors"] == ["body"]
    assert seen["body"]["format"] == "html" and seen["body"]["ttl"] == 60


async def test_fetch_per_url_error_raises_with_reason():
    def handler(request):
        return httpx.Response(200, json={"results": [], "errors": [{"url": "u", "error": "bot_blocked"}]})

    with pytest.raises(PageFetchError, match="bot_blocked"):
        await gateway_with(handler).fetch_page("http://x.test")


async def test_missing_key_raises_before_any_request(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    called = []

    def handler(request):
        called.append(request)
        return httpx.Response(200, json={})

    with pytest.raises(MissingApiKeyError):
        await gateway_with(handler, key=None).fetch_page("http://x.test")
    assert called == []


@pytest.mark.parametrize("status, code", [(401, "INVALID_API_KEY"), (402, "INSUFFICIENT_CREDITS"), (403, "FORBIDDEN")])
async def test_api_errors_are_clear_and_never_contain_the_key(status, code):
    def handler(request):
        return httpx.Response(status, json={"error": {"code": code, "message": "nope"}})

    with pytest.raises(TinyFishApiError) as caught:
        await gateway_with(handler).fetch_page("http://x.test")
    assert code in str(caught.value)
    assert KEY not in str(caught.value)


async def test_transient_error_is_retried_once():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"results": [{"text": "ok"}], "errors": []})

    page = await gateway_with(handler).fetch_page("http://x.test")
    assert page.text == "ok" and len(calls) == 2


async def test_agent_payload_and_result():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "COMPLETED", "run_id": "r1", "num_of_steps": 5, "result": {"a": 1}})

    result = await gateway_with(handler).run_agent("https://c.test", "goal", {"type": "object"}, 90)
    assert seen["path"] == "/v1/automation/run"
    assert seen["body"]["agent_config"] == {"max_duration_seconds": 90}
    assert seen["body"]["output_schema"] == {"type": "object"}
    assert (result.run_id, result.num_of_steps, result.result) == ("r1", 5, {"a": 1})


async def test_failed_agent_run_raises():
    def handler(request):
        return httpx.Response(200, json={"status": "FAILED", "run_id": "r1", "error": {"message": "site blocked"}})

    with pytest.raises(AgentRunError, match="site blocked"):
        await gateway_with(handler).run_agent("https://c.test", "goal", {}, 90)


async def test_agent_is_never_retried_because_it_costs_money():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    with pytest.raises(TinyFishApiError):
        await gateway_with(handler).run_agent("https://c.test", "goal", {}, 90)
    assert len(calls) == 1


async def test_monitor_lifecycle():
    def handler(request):
        if request.method == "POST" and request.url.path == "/v1/monitors":
            body = json.loads(request.content)
            assert body["type"] == "fetch" and body["config"]["url"] == "https://c.test"
            return httpx.Response(201, json={"monitor": {"id": "m1"}, "run": {"results": [{"text": "baseline"}], "errors": []}})
        if request.method == "POST":
            return httpx.Response(201, json={"run": {"results": [{"text": "now"}], "errors": []}})
        return httpx.Response(200, json={"deleted": True, "id": "m1"})

    gateway = gateway_with(handler)
    created = await gateway.create_monitor("https://c.test", "n", "p", "17 1 * * *")
    assert (created.monitor_id, created.baseline_text) == ("m1", "baseline")
    assert await gateway.run_monitor("m1", "https://c.test") == "now"
    assert await gateway.delete_monitor("m1") is True


async def test_monitor_gone_returns_none():
    def handler(request):
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "gone"}})

    assert await gateway_with(handler).run_monitor("m1", "https://c.test") is None


async def test_search_parses_hits_and_passes_exclusions():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"results": [{"title": "T", "url": "https://t.test", "snippet": "S"}, {"title": "no url"}]})

    hits = await gateway_with(handler).search("q", exclude_domains="a.com")
    assert seen["params"] == {"query": "q", "exclude_domains": "a.com"}
    assert [hit.url for hit in hits] == ["https://t.test"]
