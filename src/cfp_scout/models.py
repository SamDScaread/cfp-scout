"""Typed outputs for every tool. These become the tools' MCP output schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WIKICFP_ATTRIBUTION = "Data from WikiCFP (http://www.wikicfp.com), licensed CC BY-SA 3.0."


class CallSummary(BaseModel):
    event_id: int = Field(description="WikiCFP event id. Pass it to get_call or verify_deadline.")
    acronym: str = Field(description="Short name with year, for example 'NOMS 2027'.")
    title: str
    start_date: str | None = Field(description="ISO date, or null when WikiCFP lists N/A or TBD.")
    end_date: str | None
    location: str | None
    submission_deadline: str | None = Field(description="ISO date as listed on WikiCFP.")
    abstract_deadline: str | None = Field(description="ISO date, or null when none is listed.")
    wikicfp_url: str


class SearchCallsResult(BaseModel):
    topic: str
    source: Literal["category", "title_search"] = Field(
        description="'category' lists a WikiCFP category by deadline; 'title_search' matches CFP titles."
    )
    calls: list[CallSummary]
    total_in_source: int | None = Field(description="Total CFPs in the category, when WikiCFP reports it.")
    next_page: int | None = Field(
        default=None,
        description="Pass as start_page to keep reading. WikiCFP lists many small venues first, so "
        "a well-known conference may be further down, or easier to find by its name.",
    )
    related_categories: list[str] = Field(
        default_factory=list,
        description="Categories WikiCFP matched. Try one as the topic when results are thin.",
    )
    source_url: str
    attribution: str = WIKICFP_ATTRIBUTION


class CallDetail(BaseModel):
    event_id: int
    acronym: str
    title: str
    start_date: str | None
    end_date: str | None
    location: str | None
    abstract_deadline: str | None
    submission_deadline: str | None
    notification_due: str | None
    final_version_due: str | None
    categories: list[str]
    official_url: str | None = Field(description="Conference website as listed on WikiCFP, if any.")
    date_lines: list[str] = Field(
        description="Lines from the call text that mention a date, such as per-track deadlines."
    )
    wikicfp_url: str
    attribution: str = WIKICFP_ATTRIBUTION


class VenueRank(BaseModel):
    title: str
    acronym: str
    rank: str = Field(description="ICORE rank as published, for example 'A*', 'A', 'B', 'C'.")
    source: str = Field(description="Ranking edition, for example 'ICORE2026'.")
    field_of_research: str | None


class VenueRankResult(BaseModel):
    query: str
    edition: str
    is_ranked: bool = Field(
        description="False means not listed in this edition. ICORE covers computing venues, "
        "so an unlisted venue is not necessarily a poor one."
    )
    exact_matches: list[VenueRank]
    other_matches: list[VenueRank] = Field(description="Venues whose acronym only partly matches.")
    source_url: str


class VerifiedDeadline(BaseModel):
    conference_name: str
    official_url: str = Field(description="The site the Agent started from.")
    official_url_source: Literal["wikicfp", "caller", "search"]
    status: Literal["verified", "unverified", "not_found"] = Field(
        description="'verified': the date was re-read from evidence_url by Fetch. "
        "'unverified': the Agent reported a date that could not be re-read, so do not trust it. "
        "'not_found': the site does not state a deadline the Agent could find."
    )
    verification_method: Literal["quote_match", "date_match", "none"]
    deadline: str | None = Field(description="ISO date of the main paper deadline.")
    deadline_text: str | None = Field(description="The deadline as written on the site.")
    deadline_quote: str | None = Field(description="Sentence copied from the site by the Agent.")
    was_extended: bool | None = Field(description="True when the site says the deadline was extended.")
    submissions_closed: bool | None = Field(description="True when the deadline date has already passed.")
    notification_date: str | None = Field(description="ISO date, only if also found on evidence_url.")
    timezone: str | None
    evidence_url: str | None = Field(description="Open this page to check the answer yourself.")
    wikicfp_deadline: str | None = Field(description="What WikiCFP lists, for comparison.")
    matches_wikicfp: bool | None = Field(description="Null when there is nothing to compare.")
    warnings: list[str]
    agent_run_id: str | None
    agent_steps: int | None
    estimated_cost_usd: float | None = Field(description="Agent steps x the published $0.016 per step.")


class WatchInfo(BaseModel):
    monitor_id: str
    conference_name: str
    url: str
    schedule_cron: str
    tracked_lines: list[str] = Field(description="Deadline-related lines captured as the baseline.")
    note: str


class WatchCheck(BaseModel):
    monitor_id: str
    conference_name: str
    url: str
    changed: bool
    added_lines: list[str]
    removed_lines: list[str]
    tracked_lines: list[str]
    baseline_captured_at: str
    checked_at: str


class WatchStopped(BaseModel):
    monitor_id: str
    stopped: bool


class HealthCheckItem(BaseModel):
    name: str
    ok: bool
    detail: str
    duration_ms: int


class HealthReport(BaseModel):
    ok: bool = Field(description="False means at least one tool is broken right now.")
    checked_at: str
    checks: list[HealthCheckItem]
