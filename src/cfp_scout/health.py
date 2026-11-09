"""Health check: live probes that fail loudly when a site changes and a tool would break."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

from .errors import MissingApiKeyError
from .models import HealthCheckItem, HealthReport
from .service import CfpScout

AGENT_CANARY_URL = "https://2027.ieee-icra.org"
AGENT_CANARY_NAME = "ICRA 2027"
AGENT_CANARY_DEADLINE = "2026-09-16"  # In the past and stated on the site, so it should not change.
WATCH_CANARY_URL = "https://2027.ieee-icra.org/contribute/call-for-icra-2027-papers-now-accepting-submissions/"


async def _timed(name: str, probe: Callable[[], Awaitable[str]]) -> HealthCheckItem:
    started = time.monotonic()
    try:
        detail = await probe()
        ok = True
    except MissingApiKeyError:
        raise
    except Exception as exc:  # Every failure must land in the report, whatever its type.
        detail = str(exc)
        ok = False
    return HealthCheckItem(name=name, ok=ok, detail=detail, duration_ms=int((time.monotonic() - started) * 1000))


async def run_health_check(
    service: CfpScout, include_agent: bool = False, include_watch: bool = False
) -> HealthReport:
    first_event: dict[str, int] = {}

    async def category() -> str:
        result = await service.search_calls("robotics", limit=5, fresh=True)
        if result.source != "category":
            raise AssertionError("WikiCFP no longer recognises the 'robotics' category.")
        if not result.calls:
            raise AssertionError("The 'robotics' category returned no upcoming calls.")
        if not any(call.submission_deadline for call in result.calls):
            raise AssertionError("No listed call has a readable submission deadline.")
        first_event["id"] = result.calls[0].event_id
        return f"{len(result.calls)} calls parsed, {result.total_in_source} in category"

    async def event() -> str:
        if "id" not in first_event:
            raise AssertionError("Skipped because the category check failed first.")
        detail = await service.get_call(first_event["id"], fresh=True)
        if not (detail.submission_deadline or detail.start_date):
            raise AssertionError(f"Event {detail.event_id} has no readable dates.")
        return f"{detail.acronym} parsed, deadline {detail.submission_deadline}"

    async def title_search() -> str:
        from .parsers import WIKICFP_BASE, parse_title_search

        url = f"{WIKICFP_BASE}/cfp/servlet/tool.search?q=robotics&year=a"
        page = parse_title_search((await service._read(url, service._wikicfp_limiter, fresh=True)).text, "robotics")
        if not page.calls:
            raise AssertionError("Title search for 'robotics' across all years returned no calls.")
        return f"{len(page.calls)} calls parsed"

    async def rank_known() -> str:
        result = await service.get_venue_rank("ICRA", fresh=True)
        if not result.is_ranked:
            raise AssertionError("ICORE no longer returns a rank for ICRA.")
        return f"ICRA is {result.exact_matches[0].rank} in {result.edition}"

    async def rank_empty() -> str:
        result = await service.get_venue_rank("NOTAVENUEXYZ", fresh=True)
        if result.exact_matches or result.other_matches:
            raise AssertionError("A made-up acronym unexpectedly matched a venue.")
        return "empty result still recognised"

    checks = [
        await _timed("wikicfp_category_page", category),
        await _timed("wikicfp_event_page", event),
        await _timed("wikicfp_title_search", title_search),
        await _timed("icore_rank_lookup", rank_known),
        await _timed("icore_empty_result", rank_empty),
    ]

    if include_agent:

        async def agent() -> str:
            result = await service.verify_deadline(official_url=AGENT_CANARY_URL, conference_name=AGENT_CANARY_NAME)
            if result.status != "verified" or result.deadline != AGENT_CANARY_DEADLINE:
                raise AssertionError(
                    f"Expected verified {AGENT_CANARY_DEADLINE}, got {result.status} {result.deadline}."
                )
            return f"verified by {result.verification_method} in {result.agent_steps} steps"

        checks.append(await _timed("official_site_agent", agent))

    if include_watch:

        async def watch() -> str:
            info = await service.watch_deadline(WATCH_CANARY_URL, "health check canary", "0 0 1 1 *")
            try:
                if not info.tracked_lines:
                    raise AssertionError("Monitor's baseline held no dated deadline lines.")
                check = await service.check_watch(info.monitor_id)
                if not check.tracked_lines:
                    raise AssertionError("Monitor's run held no dated deadline lines.")
            finally:
                # Always delete the canary, so a failed check never leaves a schedule behind. Its cron
                # fires once a year, so even a failed delete costs at most $0.005 a year.
                if service.store.get(info.monitor_id) is not None:
                    await service.stop_watch(info.monitor_id)
            changed = "changed" if check.changed else "unchanged"
            return f"created, ran and deleted a monitor, {len(check.tracked_lines)} lines tracked, {changed}"

        checks.append(await _timed("monitor_watch_cycle", watch))

    return HealthReport(
        ok=all(check.ok for check in checks),
        checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        checks=checks,
    )


async def _run_cli(include_agent: bool, include_watch: bool = False) -> HealthReport:
    service = CfpScout()
    try:
        return await run_health_check(service, include_agent=include_agent, include_watch=include_watch)
    finally:
        await service.gateway.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cfp-scout-health",
        description="Check that every site this server depends on still parses. Exits 1 if anything broke.",
    )
    parser.add_argument(
        "--include-agent",
        action="store_true",
        help="Also run one real Agent task. Spends about $0.20 from your TinyFish wallet.",
    )
    parser.add_argument(
        "--include-watch",
        action="store_true",
        help="Also create, run and delete one Monitor. Spends about $0.01 from your TinyFish wallet.",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(_run_cli(args.include_agent, args.include_watch))
    except MissingApiKeyError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        for check in report.checks:
            print(f"{'PASS' if check.ok else 'FAIL'}  {check.name}  ({check.duration_ms} ms)  {check.detail}")
        print("HEALTHY" if report.ok else "BROKEN: a site changed or a dependency failed. See FAIL lines above.")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
