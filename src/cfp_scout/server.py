"""MCP server entry point. Start with: cfp-scout"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .health import run_health_check
from .models import (
    CallDetail,
    HealthReport,
    SearchCallsResult,
    VenueRankResult,
    VerifiedDeadline,
    WatchCheck,
    WatchInfo,
    WatchStopped,
)
from .service import DEFAULT_WATCH_CRON, CfpScout

INSTRUCTIONS = (
    "CFP Scout finds academic calls for papers on WikiCFP, ranks venues with ICORE, and checks "
    "deadlines on the official conference site. Typical flow: search_calls, then get_venue_rank to "
    "drop weak venues, then verify_deadline on the few that matter. WikiCFP listings can be stale, "
    "so treat a deadline as confirmed only when verify_deadline returns status 'verified'. "
    "verify_deadline spends wallet funds (about $0.06 to $0.21 per run), so do not call it on every result."
)


def build_server(service: CfpScout | None = None) -> MCPServer:
    scout = service or CfpScout()
    mcp = MCPServer("cfp-scout", instructions=INSTRUCTIONS)
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True)

    @mcp.tool(annotations=read_only)
    async def search_calls(
        topic: Annotated[str, Field(description="WikiCFP category or keywords, for example 'robotics' or 'embodied ai'.")],
        deadline_within_days: Annotated[
            int | None, Field(description="Only return calls whose deadline is within this many days from today.", ge=0)
        ] = None,
        limit: Annotated[int, Field(description="Maximum calls to return.", ge=1, le=50)] = 20,
        start_page: Annotated[int, Field(description="WikiCFP page to start from. Use next_page from an earlier result.", ge=1)] = 1,
    ) -> SearchCallsResult:
        """Find upcoming calls for papers on WikiCFP by topic, soonest deadline first.

        Past deadlines are left out. Listings are unverified and often include low-tier venues,
        so follow up with get_venue_rank and verify_deadline. Takes about 5 seconds per WikiCFP
        page because this server honours WikiCFP's crawl limit.
        """
        return await scout.search_calls(topic, deadline_within_days, limit, start_page)

    @mcp.tool(annotations=read_only)
    async def get_call(
        event_id: Annotated[int, Field(description="WikiCFP event id from search_calls.", gt=0)],
    ) -> CallDetail:
        """Get one call's dates, location, categories, official website and per-track date lines."""
        return await scout.get_call(event_id)

    @mcp.tool(annotations=read_only)
    async def get_venue_rank(
        acronym: Annotated[str, Field(description="Venue acronym, with or without a year, for example 'ICRA' or 'NOMS 2027'.")],
        edition: Annotated[str, Field(description="ICORE edition, such as ICORE2026 or CORE2023.")] = "ICORE2026",
    ) -> VenueRankResult:
        """Look up a conference's ICORE rank (A*, A, B, C) to judge how established it is.

        ICORE covers computing venues. is_ranked false means not listed, which is not proof of poor quality.
        """
        return await scout.get_venue_rank(acronym, edition)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True))
    async def verify_deadline(
        event_id: Annotated[int | None, Field(description="WikiCFP event id. Its official link and listed deadline are used.", gt=0)] = None,
        official_url: Annotated[str | None, Field(description="Conference website, if you already know it.")] = None,
        conference_name: Annotated[str | None, Field(description="Name such as 'ICRA 2027'. Used to find the site by search if no URL is known.")] = None,
    ) -> VerifiedDeadline:
        """Confirm the real paper deadline on the conference's official website.

        A TinyFish Agent navigates the site, then Fetch independently re-reads the page it cites.
        Only status 'verified' means the date was found on that page. Provide at least one argument.
        Takes 20 seconds to 2 minutes and costs about $0.06 to $0.21 from the TinyFish wallet.
        """
        return await scout.verify_deadline(event_id, official_url, conference_name)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True))
    async def watch_deadline(
        url: Annotated[str, Field(description="Public page stating the deadline, normally evidence_url from verify_deadline.")],
        conference_name: Annotated[str, Field(description="Name used to label the watch.")],
        schedule_cron: Annotated[str, Field(description="Five-field cron in UTC. Default is daily.")] = DEFAULT_WATCH_CRON,
    ) -> WatchInfo:
        """Start a recurring TinyFish Monitor on a deadline page, to catch extensions.

        Creates a billable schedule: $0.005 per check, about $0.15 a month when daily.
        Only call this when the user asked to track a conference. Remove it with stop_watch.
        """
        return await scout.watch_deadline(url, conference_name, schedule_cron)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True))
    async def check_watch(
        monitor_id: Annotated[str, Field(description="monitor_id returned by watch_deadline.")],
    ) -> WatchCheck:
        """Re-read a watched page now and report which deadline lines changed since the baseline. Costs $0.005."""
        return await scout.check_watch(monitor_id)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True))
    async def stop_watch(
        monitor_id: Annotated[str, Field(description="monitor_id returned by watch_deadline.")],
    ) -> WatchStopped:
        """Delete a watch and stop its charges. Only affects watches created by this server."""
        return await scout.stop_watch(monitor_id)

    @mcp.tool(annotations=read_only)
    async def health_check(
        include_agent: Annotated[bool, Field(description="Also run one real Agent task, about $0.20.")] = False,
        include_watch: Annotated[
            bool, Field(description="Also create, run and delete one Monitor, about $0.01.")
        ] = False,
    ) -> HealthReport:
        """Probe WikiCFP and ICORE live and report which tools are broken right now.

        Call this when a tool returns SITE_CHANGED or results look wrong.
        """
        return await run_health_check(scout, include_agent, include_watch)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
