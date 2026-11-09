"""The tool logic. Each method calls TinyFish for the real web work and returns typed data."""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote, quote_plus

from bs4 import BeautifulSoup

from .dates import date_spellings, find_dates, iso, parse_date
from .errors import (
    AgentBudgetError,
    AgentRunError,
    BadInputError,
    CfpScoutError,
    OfficialSiteNotFoundError,
    PageFetchError,
    WatchNotFoundError,
)
from .gateway import TinyFishGateway
from .models import (
    CallDetail,
    CallSummary,
    SearchCallsResult,
    VenueRankResult,
    VerifiedDeadline,
    WatchCheck,
    WatchInfo,
    WatchStopped,
)
from .parsers import (
    WIKICFP_BASE,
    event_url,
    parse_category_page,
    parse_event_page,
    parse_icore_page,
    parse_title_search,
)
from .watches import WatchRecord, WatchStore

AGENT_USD_PER_STEP = 0.016
AGENT_MAX_DURATION_SECONDS = 100
DEFAULT_MAX_AGENT_RUNS = 20
WIKICFP_MIN_INTERVAL_SECONDS = 5.0  # WikiCFP asks for at most one query every five seconds.
ICORE_MIN_INTERVAL_SECONDS = 1.0
MAX_CATEGORY_PAGES = 3
PAGE_CACHE_TTL_SECONDS = 3600
VERIFY_CACHE_TTL_SECONDS = 6 * 3600
DEFAULT_WATCH_CRON = "17 1 * * *"
_SEARCH_EXCLUDED = "wikicfp.com,conferenceindex.org,allconferencealert.com,waset.org,facebook.com,linkedin.com,x.com"
_TRACKED_LINE = re.compile(r"deadline|due|extend|submission|notification", re.I)

_AGENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "conference_name": {"type": "string"},
        "main_paper_deadline": {"type": "string", "nullable": True},
        "deadline_quote": {"type": "string", "nullable": True},
        "notification_date": {"type": "string", "nullable": True},
        "timezone": {"type": "string", "nullable": True},
        "evidence_url": {"type": "string"},
        "deadline_was_extended": {"type": "boolean"},
    },
    "required": ["conference_name", "main_paper_deadline", "evidence_url", "deadline_was_extended"],
}


def _agent_goal(conference_name: str | None) -> str:
    subject = f"{conference_name}" if conference_name else "this conference"
    return (
        f"Find the official submission deadline for the main full papers of {subject}, "
        "including any extension announced on the site. Open the call for papers, important dates "
        "or announcements pages if needed. Set deadline_quote to the exact sentence or table row "
        "from the page that states the deadline, copied word for word. Set evidence_url to the "
        "page where that text appears. Report dates exactly as written on the site. "
        "If something is not stated, return null, and do not guess. Stop as soon as you have found it. "
        "Do not submit, register or log in to anything."
    )


def _null_if_empty(value: Any) -> str | None:
    """The Agent sometimes returns the string 'null' for a nullable field."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return None if cleaned.lower() in {"", "null", "none", "n/a", "not stated"} else cleaned


def _timezone_on_page(text: str | None, page_text: str) -> str | None:
    """Keep a timezone only if the page states it. The Agent inferred one for ICRAI 2026 from its venue."""
    if not text or not page_text:
        return None
    for part in re.split(r"[()]", text):
        needle = _normalize(part)
        if needle and re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", page_text):
            return text
    return None


def _normalize(text: str) -> str:
    """Lowercase and drop markdown marks, so a quote matches however the page was rendered."""
    without_marks = re.sub(r"[*_~`|\\]", " ", text.lower().replace("&amp;", "&"))
    return re.sub(r"\s+", " ", without_marks).strip()


def _base_acronym(name: str) -> str:
    """'IEEE-RICAI 2026' becomes 'RICAI'; 'NOMS 2027' becomes 'NOMS'."""
    value = re.sub(r"\b(19|20)\d{2}\b", "", name).strip()
    value = re.sub(r"^(IEEE|ACM|IFIP)[-\s]+", "", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def extract_tracked_lines(text: str, limit: int = 40) -> list[str]:
    """Pick the lines that state a date and talk about deadlines, for change detection."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", re.sub(r"[*_~`|#>]", " ", raw)).strip()
        if line and _TRACKED_LINE.search(line) and find_dates(line) and line not in lines:
            lines.append(line[:240])
        if len(lines) >= limit:
            break
    return lines


class _Limiter:
    """Enforces a minimum gap between requests to one site."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


class CfpScout:
    def __init__(
        self,
        gateway: TinyFishGateway | None = None,
        *,
        store: WatchStore | None = None,
        today: Callable[[], date] = lambda: datetime.now(timezone.utc).date(),
        wikicfp_interval: float = WIKICFP_MIN_INTERVAL_SECONDS,
        icore_interval: float = ICORE_MIN_INTERVAL_SECONDS,
        max_agent_runs: int | None = None,
    ) -> None:
        self.gateway = gateway or TinyFishGateway()
        self.store = store or WatchStore()
        self._today = today
        self._wikicfp_limiter = _Limiter(wikicfp_interval)
        self._icore_limiter = _Limiter(icore_interval)
        self._page_cache: dict[str, tuple[float, Any]] = {}
        self._verify_cache: dict[str, tuple[float, VerifiedDeadline]] = {}
        self._agent_runs = 0
        self._max_agent_runs = (
            max_agent_runs
            if max_agent_runs is not None
            else int(os.environ.get("CFP_SCOUT_MAX_AGENT_RUNS", DEFAULT_MAX_AGENT_RUNS))
        )

    async def _read(self, url: str, limiter: _Limiter, *, fresh: bool = False):
        cached = self._page_cache.get(url)
        if cached and not fresh and time.monotonic() - cached[0] < PAGE_CACHE_TTL_SECONDS:
            return cached[1]
        await limiter.wait()
        page = await self.gateway.fetch_page(url, ttl=0 if fresh else PAGE_CACHE_TTL_SECONDS)
        self._page_cache[url] = (time.monotonic(), page)
        return page

    async def search_calls(
        self,
        topic: str,
        deadline_within_days: int | None = None,
        limit: int = 20,
        start_page: int = 1,
        *,
        fresh: bool = False,
    ) -> SearchCallsResult:
        topic = topic.strip()
        if not topic:
            raise BadInputError("topic must not be empty.")
        if not 1 <= limit <= 50:
            raise BadInputError("limit must be between 1 and 50.")
        if deadline_within_days is not None and deadline_within_days < 0:
            raise BadInputError("deadline_within_days must not be negative.")
        if start_page < 1:
            raise BadInputError("start_page must be 1 or higher.")
        today = self._today()
        cutoff = today + timedelta(days=deadline_within_days) if deadline_within_days is not None else None

        def wanted(call: CallSummary) -> bool:
            deadline = parse_date(call.submission_deadline)
            if deadline is None:
                return cutoff is None
            return deadline >= today and (cutoff is None or deadline <= cutoff)

        collected: list[CallSummary] = []
        total: int | None = None
        next_page: int | None = None
        category_url = f"{WIKICFP_BASE}/cfp/call?conference={quote(topic)}"
        category_found = False
        for number in range(start_page, start_page + MAX_CATEGORY_PAGES):
            url = category_url if number == 1 else f"{category_url}&page={number}"
            page = parse_category_page((await self._read(url, self._wikicfp_limiter, fresh=fresh)).text, topic)
            if not page.found:
                break
            category_found = True
            total = page.total
            collected += [call for call in page.calls if wanted(call)]
            past_cutoff = bool(cutoff) and any(
                (parse_date(call.submission_deadline) or date.min) > cutoff for call in page.calls
            )
            pages_remain = bool(page.pages) and number < page.pages
            next_page = number + 1 if pages_remain and not past_cutoff else None
            if len(collected) > limit:
                next_page = number
            if len(collected) >= limit or next_page is None:
                break
        if category_found:
            return SearchCallsResult(
                topic=topic,
                source="category",
                calls=collected[:limit],
                total_in_source=total,
                next_page=next_page,
                source_url=category_url,
            )

        search_url = f"{WIKICFP_BASE}/cfp/servlet/tool.search?q={quote_plus(topic)}&year=f"
        found = parse_title_search((await self._read(search_url, self._wikicfp_limiter, fresh=fresh)).text, topic)
        matches = sorted(
            (call for call in found.calls if wanted(call)),
            key=lambda call: call.submission_deadline or "9999",
        )
        return SearchCallsResult(
            topic=topic,
            source="title_search",
            calls=matches[:limit],
            total_in_source=len(found.calls),
            related_categories=found.related_categories,
            source_url=search_url,
        )

    async def get_call(self, event_id: int, *, fresh: bool = False) -> CallDetail:
        if event_id <= 0:
            raise BadInputError("event_id must be a positive integer returned by search_calls.")
        page = await self._read(event_url(event_id), self._wikicfp_limiter, fresh=fresh)
        return parse_event_page(page.text, event_id, page.title)

    async def get_venue_rank(self, acronym: str, edition: str = "ICORE2026", *, fresh: bool = False) -> VenueRankResult:
        query = _base_acronym(acronym)
        if not query:
            raise BadInputError("acronym must not be empty.")
        url = (
            "https://portal.core.edu.au/conf-ranks/"
            f"?search={quote_plus(query)}&by=acronym&source={quote_plus(edition)}&sort=atitle&page=1"
        )
        page = parse_icore_page((await self._read(url, self._icore_limiter, fresh=fresh)).text, query)
        exact = [rank for rank in page.ranks if rank.acronym.casefold() == query.casefold()]
        other = [rank for rank in page.ranks if rank.acronym.casefold() != query.casefold()]
        is_ranked = any(not rank.rank.lower().startswith(("unranked", "not ranked")) for rank in exact)
        return VenueRankResult(
            query=query, edition=edition, is_ranked=is_ranked, exact_matches=exact, other_matches=other, source_url=url
        )

    async def _find_official_site(self, name: str) -> str:
        acronym = _base_acronym(name).lower()
        hits = await self.gateway.search(
            f"{name} official website call for papers important dates", exclude_domains=_SEARCH_EXCLUDED
        )
        for hit in hits:
            haystack = f"{hit.title} {hit.url}".lower()
            if acronym and acronym.split()[0] in haystack:
                return hit.url
        raise OfficialSiteNotFoundError(
            f"Search found no official site for '{name}'.",
            hint="Pass official_url directly if you know the conference website.",
        )

    async def verify_deadline(
        self,
        event_id: int | None = None,
        official_url: str | None = None,
        conference_name: str | None = None,
    ) -> VerifiedDeadline:
        if event_id is None and not official_url and not conference_name:
            raise BadInputError("Provide event_id, official_url or conference_name.")

        wikicfp_deadline: str | None = None
        name = conference_name
        source = "caller"
        url = official_url
        warnings: list[str] = []
        if event_id is not None:
            call = await self.get_call(event_id)
            wikicfp_deadline = call.submission_deadline
            name = name or call.acronym
            if not url and call.official_url:
                url = call.official_url
                source = "wikicfp"

        # Fetch is free, so check the link before spending wallet funds on an Agent run.
        if url:
            try:
                await self.gateway.fetch_page(url, format="markdown", body_only=False)
            except PageFetchError as exc:
                if "blocked" not in exc.message.lower() and source == "wikicfp" and name:
                    warnings.append(f"The link listed on WikiCFP could not be read ({url}), so Search was used instead.")
                    url = None
        if not url:
            if not name:
                raise OfficialSiteNotFoundError(
                    "No official site is known for this request.", hint="Pass official_url or conference_name."
                )
            url = await self._find_official_site(name)
            source = "search"
            warnings.append("The site was found by web search. Confirm it is the right conference.")

        cached = self._verify_cache.get(url)
        if cached and time.monotonic() - cached[0] < VERIFY_CACHE_TTL_SECONDS:
            return cached[1].model_copy(update={"wikicfp_deadline": wikicfp_deadline, "matches_wikicfp": self._compare(cached[1].deadline, wikicfp_deadline)})

        if self._agent_runs >= self._max_agent_runs:
            raise AgentBudgetError(
                f"This server has already started {self._agent_runs} Agent runs, the limit for one process.",
                hint="Restart the server, or raise CFP_SCOUT_MAX_AGENT_RUNS if the spend is intended.",
            )
        self._agent_runs += 1
        run = await self.gateway.run_agent(url, _agent_goal(name), _AGENT_SCHEMA, AGENT_MAX_DURATION_SECONDS)
        verified = await self._check_agent_answer(run, url, source, name, wikicfp_deadline, warnings)
        self._verify_cache[url] = (time.monotonic(), verified)
        return verified

    @staticmethod
    def _compare(deadline: str | None, wikicfp_deadline: str | None) -> bool | None:
        return deadline == wikicfp_deadline if deadline and wikicfp_deadline else None

    async def _check_agent_answer(self, run, url, source, name, wikicfp_deadline, warnings) -> VerifiedDeadline:
        answer = run.result
        deadline_text = _null_if_empty(answer.get("main_paper_deadline"))
        quote_text = _null_if_empty(answer.get("deadline_quote"))
        evidence_url = _null_if_empty(answer.get("evidence_url"))
        timezone_text = _null_if_empty(answer.get("timezone"))
        notification_text = _null_if_empty(answer.get("notification_date"))
        deadline = parse_date(deadline_text) or parse_date(quote_text)
        status = "not_found"
        method = "none"
        page_text = ""

        if evidence_url and not evidence_url.lower().startswith(("http://", "https://")):
            warnings.append(f"The Agent returned an invalid evidence URL: {evidence_url}.")
            evidence_url = None

        if deadline_text or quote_text:
            status = "unverified"
            if deadline is None:
                warnings.append(f"Could not read a date from the Agent's answer: {deadline_text or quote_text}.")
            if evidence_url:
                try:
                    # Read the whole body: cleaned markdown can drop sidebars, and on real conference
                    # sites (ICRAI 2026, for one) that is exactly where the important dates live.
                    page = await self.gateway.fetch_page(evidence_url, format="html", body_only=True, ttl=0)
                    page_text = _normalize(BeautifulSoup(page.text, "html.parser").get_text(" "))
                except PageFetchError as exc:
                    warnings.append(f"Could not re-read the evidence page: {exc.message}")
            else:
                warnings.append("The Agent gave no evidence page, so its answer could not be re-read.")
            if page_text and deadline is not None:
                spellings = [_normalize(item) for item in date_spellings(deadline)]
                date_on_page = any(item in page_text for item in spellings)
                if quote_text and _normalize(quote_text) in page_text and find_dates(quote_text):
                    status, method = "verified", "quote_match"
                elif date_on_page:
                    status, method = "verified", "date_match"
                else:
                    warnings.append("The Agent's date does not appear on the evidence page. Do not rely on it.")

        notification: str | None = None
        parsed_notification = parse_date(notification_text)
        if parsed_notification and page_text:
            if any(_normalize(item) in page_text for item in date_spellings(parsed_notification)):
                notification = iso(parsed_notification)

        reported_extended = answer.get("deadline_was_extended")
        page_mentions_extension = "extend" in page_text
        if not isinstance(reported_extended, bool):
            was_extended = True if page_mentions_extension and "deadline" in page_text else None
        elif reported_extended and page_text and not page_mentions_extension:
            was_extended = None
            warnings.append("The Agent reported an extension, but the evidence page does not mention one.")
        else:
            was_extended = reported_extended

        comparison = self._compare(iso(deadline), wikicfp_deadline) if status == "verified" else None
        if comparison is False:
            warnings.append(
                f"The official site says {iso(deadline)} but WikiCFP lists {wikicfp_deadline}. Trust the official site."
            )
        steps = run.num_of_steps
        return VerifiedDeadline(
            conference_name=_null_if_empty(answer.get("conference_name")) or name or url,
            official_url=url,
            official_url_source=source,
            status=status,
            verification_method=method,
            deadline=iso(deadline) if status == "verified" else None,
            deadline_text=deadline_text,
            deadline_quote=quote_text,
            was_extended=was_extended,
            submissions_closed=(deadline < self._today()) if deadline and status == "verified" else None,
            notification_date=notification,
            timezone=_timezone_on_page(timezone_text, page_text),
            evidence_url=evidence_url,
            wikicfp_deadline=wikicfp_deadline,
            matches_wikicfp=comparison,
            warnings=warnings,
            agent_run_id=run.run_id,
            agent_steps=steps,
            estimated_cost_usd=round(steps * AGENT_USD_PER_STEP, 3) if steps is not None else None,
        )

    async def watch_deadline(self, url: str, conference_name: str, schedule_cron: str = DEFAULT_WATCH_CRON) -> WatchInfo:
        if not url.lower().startswith(("http://", "https://")):
            raise BadInputError("url must be a public http or https page, such as evidence_url from verify_deadline.")
        created = await self.gateway.create_monitor(
            url,
            f"CFP deadline: {conference_name}",
            "A paper submission deadline changes or is extended.",
            schedule_cron,
        )
        lines = extract_tracked_lines(created.baseline_text)
        self.store.put(
            WatchRecord(
                monitor_id=created.monitor_id,
                conference_name=conference_name,
                url=url,
                schedule_cron=schedule_cron,
                baseline_lines=lines,
                baseline_captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
        )
        warning = (
            ""
            if lines
            else " No dated deadline lines were found in this page's main content, so changes may go unnoticed. "
            "Prefer a dedicated call for papers or important dates page."
        )
        return WatchInfo(
            monitor_id=created.monitor_id,
            conference_name=conference_name,
            url=url,
            schedule_cron=schedule_cron,
            tracked_lines=lines,
            note=(
                "Each check costs $0.005 from the TinyFish wallet, about $0.15 a month when run daily. "
                "Call stop_watch when the deadline has passed." + warning
            ),
        )

    async def check_watch(self, monitor_id: str) -> WatchCheck:
        record = self.store.get(monitor_id)
        if record is None:
            raise WatchNotFoundError(
                f"No watch with id {monitor_id} on this machine.", hint="Create one with watch_deadline."
            )
        text = await self.gateway.run_monitor(monitor_id, record.url)
        if text is None:
            self.store.delete(monitor_id)
            raise WatchNotFoundError(
                f"Monitor {monitor_id} no longer exists on TinyFish, so its local record was removed.",
                hint="Create a new one with watch_deadline.",
            )
        current = extract_tracked_lines(text)
        added = [line for line in current if line not in record.baseline_lines]
        removed = [line for line in record.baseline_lines if line not in current]
        return WatchCheck(
            monitor_id=monitor_id,
            conference_name=record.conference_name,
            url=record.url,
            changed=bool(added or removed),
            added_lines=added,
            removed_lines=removed,
            tracked_lines=current,
            baseline_captured_at=record.baseline_captured_at,
            checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    async def stop_watch(self, monitor_id: str) -> WatchStopped:
        if self.store.get(monitor_id) is None:
            raise WatchNotFoundError(
                f"No watch with id {monitor_id} on this machine.",
                hint="Only watches created by this server can be stopped here.",
            )
        await self.gateway.delete_monitor(monitor_id)
        self.store.delete(monitor_id)
        return WatchStopped(monitor_id=monitor_id, stopped=True)


__all__ = ["CfpScout", "CfpScoutError", "AgentRunError", "extract_tracked_lines"]
