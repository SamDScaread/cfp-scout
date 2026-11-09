"""Thin client for the TinyFish endpoints this server uses: Fetch, Search, Agent, Monitor."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import AgentRunError, MissingApiKeyError, PageFetchError, TinyFishApiError

FETCH_URL = "https://api.fetch.tinyfish.ai"
SEARCH_URL = "https://api.search.tinyfish.ai"
AGENT_BASE = "https://agent.tinyfish.ai"
_RETRY_STATUS = {429, 500, 502, 503, 504}
_RETRY_DELAY_SECONDS = 2.0


@dataclass
class FetchedPage:
    url: str
    final_url: str | None
    title: str | None
    text: str


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


@dataclass
class AgentResult:
    run_id: str | None
    result: dict[str, Any]
    num_of_steps: int | None


@dataclass
class CreatedMonitor:
    monitor_id: str
    baseline_text: str


class TinyFishGateway:
    """Reads TINYFISH_API_KEY when a call is made, so the server can start and list tools without it."""

    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_delay: float = _RETRY_DELAY_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._retry_delay = retry_delay
        self._client = httpx.AsyncClient(transport=transport, timeout=150.0)

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        key = self._api_key or os.environ.get("TINYFISH_API_KEY", "").strip()
        if not key:
            raise MissingApiKeyError(
                "TINYFISH_API_KEY is not set.",
                hint="Create a key at https://agent.tinyfish.ai/api-keys and set it in the MCP client's env config.",
            )
        return {"X-API-Key": key}

    async def _request(self, method: str, url: str, *, retry: bool = True, timeout: float | None = None, **kwargs: Any) -> httpx.Response:
        headers = self._headers()
        attempts = 2 if retry else 1
        for attempt in range(attempts):
            is_last = attempt == attempts - 1
            try:
                response = await self._client.request(
                    method, url, headers=headers, timeout=timeout or 150.0, **kwargs
                )
            except httpx.TimeoutException as exc:
                if is_last:
                    raise TinyFishApiError(
                        f"TinyFish timed out on {method} {url}.",
                        hint="Retry shortly. If this repeats, check https://agent.tinyfish.ai.",
                    ) from exc
            except httpx.HTTPError as exc:
                if is_last:
                    raise TinyFishApiError(
                        f"Could not reach TinyFish: {type(exc).__name__}.",
                        hint="Check the network connection, then retry.",
                    ) from exc
            else:
                if response.status_code not in _RETRY_STATUS or is_last:
                    return response
            await asyncio.sleep(self._retry_delay)
        raise TinyFishApiError("TinyFish request failed after retry.")  # pragma: no cover

    @staticmethod
    def _raise_for_status(response: httpx.Response, action: str) -> None:
        if response.is_success:
            return
        code = None
        message = None
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message")
            elif isinstance(error, str):
                message = error
        except ValueError:
            pass
        status = response.status_code
        hints = {
            401: "Check that TINYFISH_API_KEY is valid at https://agent.tinyfish.ai/api-keys.",
            402: "Agent and Monitor need wallet funds. Check https://agent.tinyfish.ai/wallet.",
            403: "This account is not allowed to use this feature.",
            429: "Rate limited by TinyFish. Wait a minute, then retry.",
        }
        detail = f"{action} failed with HTTP {status}"
        if code:
            detail += f" ({code})"
        if message:
            detail += f": {message}"
        raise TinyFishApiError(detail + ".", hint=hints.get(status, "Retry shortly."))

    async def fetch_page(
        self, url: str, *, format: str = "html", body_only: bool = True, ttl: int | None = None
    ) -> FetchedPage:
        """Read one page. body_only returns verbatim HTML, which keeps the links parsers need."""
        payload: dict[str, Any] = {"urls": [url], "format": format, "per_url_timeout_ms": 60000}
        if body_only:
            payload["include_selectors"] = ["body"]
        if ttl is not None:
            payload["ttl"] = ttl
        response = await self._request("POST", FETCH_URL, json=payload)
        self._raise_for_status(response, "Fetch")
        data = response.json()
        results = data.get("results") or []
        if not results or results[0].get("text") in (None, ""):
            errors = data.get("errors") or []
            reason = errors[0].get("error", "no content") if errors else "no content"
            if isinstance(reason, dict):
                reason = reason.get("code") or reason.get("message") or "unknown"
            raise PageFetchError(
                f"TinyFish Fetch could not read {url}: {reason}.",
                hint="Open the URL in a browser to check it, then retry.",
            )
        first = results[0]
        return FetchedPage(
            url=first.get("url", url),
            final_url=first.get("final_url"),
            title=first.get("title"),
            text=first["text"],
        )

    async def search(self, query: str, *, exclude_domains: str | None = None) -> list[SearchHit]:
        params: dict[str, Any] = {"query": query}
        if exclude_domains:
            params["exclude_domains"] = exclude_domains
        response = await self._request("GET", SEARCH_URL, params=params, timeout=30.0)
        self._raise_for_status(response, "Search")
        return [
            SearchHit(title=item.get("title") or "", url=item.get("url") or "", snippet=item.get("snippet") or "")
            for item in response.json().get("results") or []
            if item.get("url")
        ]

    async def run_agent(
        self, url: str, goal: str, output_schema: dict[str, Any], max_duration_seconds: int
    ) -> AgentResult:
        """Run one Agent task. Never retried automatically, because each run spends wallet funds."""
        payload = {
            "url": url,
            "goal": goal,
            "output_schema": output_schema,
            "browser_profile": "lite",
            "agent_config": {"max_duration_seconds": max_duration_seconds},
        }
        response = await self._request(
            "POST",
            f"{AGENT_BASE}/v1/automation/run",
            retry=False,
            timeout=max_duration_seconds + 60.0,
            json=payload,
        )
        self._raise_for_status(response, "Agent run")
        data = response.json()
        status = data.get("status")
        if status != "COMPLETED":
            error = data.get("error") or {}
            reason = error.get("message") if isinstance(error, dict) else str(error)
            raise AgentRunError(
                f"Agent run on {url} ended with status {status}: {reason or 'no reason given'}.",
                hint="Check the official URL, or open the site and read the deadline directly.",
            )
        result = data.get("result")
        if not isinstance(result, dict):
            raise AgentRunError(
                f"Agent run on {url} completed without structured output.",
                hint="Retry once. If it repeats, the site may be blocking the agent.",
            )
        return AgentResult(
            run_id=data.get("run_id"), result=result, num_of_steps=data.get("num_of_steps")
        )

    @staticmethod
    def _run_text(run: dict[str, Any], url: str) -> str:
        results = run.get("results") or []
        if results and isinstance(results[0].get("text"), str) and results[0]["text"]:
            return results[0]["text"]
        errors = run.get("errors") or []
        reason = errors[0].get("error", "no content") if errors else "no content"
        raise PageFetchError(
            f"TinyFish Monitor could not read {url}: {reason}.",
            hint="Open the URL in a browser to check it, then retry.",
        )

    async def create_monitor(self, url: str, name: str, purpose: str, schedule_cron: str) -> CreatedMonitor:
        payload = {
            "type": "fetch",
            "name": name[:100],
            "config": {"url": url, "format": "markdown"},
            "schedule_cron": schedule_cron,
            "purpose": purpose,
        }
        response = await self._request("POST", f"{AGENT_BASE}/v1/monitors", retry=False, json=payload)
        self._raise_for_status(response, "Create monitor")
        data = response.json()
        return CreatedMonitor(
            monitor_id=data["monitor"]["id"], baseline_text=self._run_text(data.get("run") or {}, url)
        )

    async def run_monitor(self, monitor_id: str, url: str) -> str | None:
        """Run a monitor now. Returns the page text, or None if the monitor no longer exists."""
        response = await self._request("POST", f"{AGENT_BASE}/v1/monitors/{monitor_id}/runs", retry=False)
        if response.status_code == 404:
            return None
        self._raise_for_status(response, "Run monitor")
        return self._run_text(response.json().get("run") or {}, url)

    async def delete_monitor(self, monitor_id: str) -> bool:
        """Delete a monitor. Returns False if it was already gone."""
        response = await self._request("DELETE", f"{AGENT_BASE}/v1/monitors/{monitor_id}")
        if response.status_code == 404:
            return False
        self._raise_for_status(response, "Delete monitor")
        return True
