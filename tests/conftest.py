from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cfp_scout.gateway import AgentResult, CreatedMonitor, FetchedPage, SearchHit
from cfp_scout.errors import PageFetchError
from cfp_scout.service import CfpScout
from cfp_scout.watches import WatchStore

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 4)


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeGateway:
    """Stands in for TinyFish. Pages are keyed by a substring of the requested URL."""

    def __init__(self) -> None:
        self.pages: dict[str, str] = {}
        self.blocked: dict[str, str] = {}
        self.fetches: list[str] = []
        self.searches: list[str] = []
        self.search_hits: list[SearchHit] = []
        self.agent_answer: dict | None = None
        self.agent_calls: list[tuple[str, str]] = []
        self.agent_steps = 5
        self.monitor_text = ""
        self.monitor_gone = False
        self.deleted: list[str] = []

    async def fetch_page(self, url, *, format="html", body_only=True, ttl=None):
        self.fetches.append(url)
        for key, reason in self.blocked.items():
            if key in url:
                raise PageFetchError(f"TinyFish Fetch could not read {url}: {reason}.")
        for key, text in self.pages.items():
            if key in url:
                return FetchedPage(url=url, final_url=url, title=None, text=text)
        raise PageFetchError(f"TinyFish Fetch could not read {url}: page_not_found.")

    async def search(self, query, *, exclude_domains=None):
        self.searches.append(query)
        return self.search_hits

    async def run_agent(self, url, goal, output_schema, max_duration_seconds):
        self.agent_calls.append((url, goal))
        return AgentResult(run_id="run-1", result=self.agent_answer or {}, num_of_steps=self.agent_steps)

    async def create_monitor(self, url, name, purpose, schedule_cron):
        return CreatedMonitor(monitor_id="mon-1", baseline_text=self.monitor_text)

    async def run_monitor(self, monitor_id, url):
        return None if self.monitor_gone else self.monitor_text

    async def delete_monitor(self, monitor_id):
        self.deleted.append(monitor_id)
        return True

    async def close(self):
        pass


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def scout(gateway, tmp_path) -> CfpScout:
    return CfpScout(
        gateway,
        store=WatchStore(tmp_path / "watches.json"),
        today=lambda: TODAY,
        wikicfp_interval=0,
        icore_interval=0,
        max_agent_runs=3,
    )
