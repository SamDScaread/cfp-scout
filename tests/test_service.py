import pytest
from conftest import load

from cfp_scout.errors import AgentBudgetError, OfficialSiteNotFoundError, WatchNotFoundError
from cfp_scout.gateway import SearchHit
from cfp_scout.service import extract_tracked_lines


async def test_search_calls_uses_category_and_drops_past_deadlines(scout, gateway):
    gateway.pages["call?conference=robotics"] = load("category_robotics.html")
    result = await scout.search_calls("robotics", limit=2)
    assert result.source == "category"
    assert result.total_in_source == 3237
    assert [call.event_id for call in result.calls] == [190921, 191951]
    assert "CC BY-SA" in result.attribution


async def test_deadline_window_filters_and_stops_paging(scout, gateway):
    gateway.pages["call?conference=robotics"] = load("category_robotics.html")
    result = await scout.search_calls("robotics", deadline_within_days=30)
    assert [call.event_id for call in result.calls] == [190921, 191951]
    assert len(gateway.fetches) == 1


async def test_paging_reports_where_to_continue(scout, gateway):
    gateway.pages["call?conference=robotics"] = load("category_robotics.html")
    result = await scout.search_calls("robotics", limit=2)
    assert result.next_page == 1  # The page held more matches than the limit allowed.
    result = await scout.search_calls("robotics", limit=3, start_page=2)
    assert gateway.fetches[-1].endswith("&page=2")
    assert result.next_page == 3


async def test_past_cutoff_ends_paging(scout, gateway):
    gateway.pages["call?conference=robotics"] = load("category_robotics.html")
    result = await scout.search_calls("robotics", deadline_within_days=30)
    assert result.next_page is None


async def test_unknown_category_falls_back_to_title_search(scout, gateway):
    gateway.pages["call?conference=embodied%20robotics"] = load("category_unknown_redirects_home.html")
    gateway.pages["tool.search?q=embodied+robotics"] = load("title_search.html")
    result = await scout.search_calls("embodied robotics")
    assert result.source == "title_search"
    assert [call.acronym for call in result.calls] == ["IEEE-RICAI 2026", "FLAIRS-40 Embodied AI Special Track 2027"]
    assert "robotics" in result.related_categories


async def test_page_cache_avoids_repeat_requests(scout, gateway):
    gateway.pages["eventid=204130"] = load("event_flairs.html")
    await scout.get_call(204130)
    await scout.get_call(204130)
    assert len(gateway.fetches) == 1


@pytest.mark.parametrize(
    "kwargs", [{"topic": "  "}, {"topic": "x", "limit": 0}, {"topic": "x", "limit": 51}, {"topic": "x", "deadline_within_days": -1}, {"topic": "x", "start_page": 0}]
)
async def test_bad_search_input_is_rejected(scout, kwargs):
    with pytest.raises(ValueError):
        await scout.search_calls(**kwargs)


async def test_venue_rank_strips_year_and_prefix(scout, gateway):
    gateway.pages["search=IROS"] = load("icore_iros.html")
    result = await scout.get_venue_rank("IEEE-IROS 2027")
    assert result.query == "IROS"
    assert result.is_ranked and result.exact_matches[0].rank == "A"


async def test_unlisted_venue_is_not_ranked(scout, gateway):
    gateway.pages["search=NOTAVENUEXYZ"] = load("icore_empty.html")
    result = await scout.get_venue_rank("NOTAVENUEXYZ")
    assert not result.is_ranked and result.exact_matches == []


ICRA_ANSWER = {
    "conference_name": "ICRA 2027",
    "main_paper_deadline": "September 16, 2026 (23:59 PST) - extended to this date from an earlier deadline",
    "deadline_quote": "Paper submission deadline: September 16, 2026 (23:59 PST)",
    "notification_date": "January 31, 2027 (Sun)",
    "timezone": "PST",
    "evidence_url": "https://2027.ieee-icra.org/contribute/call/",
    "deadline_was_extended": True,
}


async def test_verify_with_real_icra_answer(scout, gateway):
    gateway.pages["2027.ieee-icra.org"] = load("evidence_icra.md")
    gateway.agent_answer = dict(ICRA_ANSWER)
    gateway.agent_steps = 9
    result = await scout.verify_deadline(official_url="https://2027.ieee-icra.org", conference_name="ICRA 2027")
    assert result.status == "verified"
    assert result.verification_method == "quote_match"
    assert result.deadline == "2026-09-16"
    assert result.was_extended is True
    assert result.submissions_closed is True
    assert result.notification_date == "2027-01-31"
    assert result.estimated_cost_usd == 0.144
    assert result.official_url_source == "caller"


async def test_string_null_from_agent_becomes_real_null(scout, gateway):
    gateway.pages["2027.ieee-icra.org"] = load("evidence_icra.md")
    gateway.agent_answer = {**ICRA_ANSWER, "timezone": "null", "notification_date": "null"}
    result = await scout.verify_deadline(official_url="https://2027.ieee-icra.org")
    assert result.timezone is None and result.notification_date is None


async def test_date_match_when_quote_was_reworded(scout, gateway):
    gateway.pages["xaiworldconference.com"] = load("evidence_xai.md")
    gateway.agent_answer = {
        "conference_name": "XAI World Conference 2027",
        "main_paper_deadline": "1st of February, 2027",
        "deadline_quote": "Papers must be uploaded by the first of February",
        "evidence_url": "https://xaiworldconference.com/2027/important-dates/",
        "deadline_was_extended": False,
    }
    result = await scout.verify_deadline(official_url="https://xaiworldconference.com/2027/")
    assert (result.status, result.verification_method, result.deadline) == ("verified", "date_match", "2027-02-01")
    assert result.was_extended is False
    assert result.submissions_closed is False


async def test_invented_date_is_flagged_and_withheld(scout, gateway):
    gateway.pages["noms2027"] = load("evidence_noms.md")
    gateway.agent_answer = {
        "conference_name": "NOMS 2027",
        "main_paper_deadline": "December 25, 2026",
        "deadline_quote": "Deadline: December 25, 2026",
        "evidence_url": "https://noms2027.ieee-noms.org/authors/call",
        "deadline_was_extended": False,
    }
    result = await scout.verify_deadline(official_url="https://noms2027.ieee-noms.org")
    assert result.status == "unverified"
    assert result.deadline is None
    assert result.submissions_closed is None
    assert any("does not appear" in warning for warning in result.warnings)


async def test_unbacked_extension_claim_is_dropped(scout, gateway):
    gateway.pages["noms2027"] = load("evidence_noms.md")
    gateway.agent_answer = {
        "conference_name": "NOMS 2027",
        "main_paper_deadline": "9 November 2026",
        "evidence_url": "https://noms2027.ieee-noms.org/authors/call",
        "deadline_was_extended": True,
    }
    result = await scout.verify_deadline(official_url="https://noms2027.ieee-noms.org")
    assert result.status == "verified"
    assert result.was_extended is None
    assert any("extension" in warning for warning in result.warnings)


async def test_no_deadline_on_site_is_not_found(scout, gateway):
    gateway.pages["example.org"] = "A site with no dates."
    gateway.agent_answer = {
        "conference_name": "Some Conf",
        "main_paper_deadline": None,
        "evidence_url": "https://example.org/",
        "deadline_was_extended": False,
    }
    result = await scout.verify_deadline(official_url="https://example.org/")
    assert result.status == "not_found" and result.deadline is None


async def test_event_id_uses_wikicfp_link_and_reports_mismatch(scout, gateway):
    gateway.pages["eventid=204130"] = load("event_flairs.html")
    gateway.pages["example.org"] = "Important dates: full papers due February 8, 2027 after an extension."
    gateway.agent_answer = {
        "conference_name": "FLAIRS",
        "main_paper_deadline": "February 8, 2027",
        "evidence_url": "https://example.org/flairs-special-track/",
        "deadline_was_extended": True,
    }
    result = await scout.verify_deadline(event_id=204130)
    assert result.official_url_source == "wikicfp"
    assert result.wikicfp_deadline == "2027-02-01"
    assert result.matches_wikicfp is False
    assert any("Trust the official site" in warning for warning in result.warnings)


async def test_dead_wikicfp_link_falls_back_to_search(scout, gateway):
    gateway.pages["eventid=204130"] = load("event_flairs.html")
    gateway.blocked["example.org"] = "page_not_found"
    gateway.search_hits = [
        SearchHit(title="Unrelated", url="https://unrelated.test/", snippet=""),
        SearchHit(title="DGAI-FLAIRS special track", url="https://flairs.test/track", snippet=""),
    ]
    gateway.pages["flairs.test"] = "Papers due February 1, 2027."
    gateway.agent_answer = {
        "conference_name": "FLAIRS",
        "main_paper_deadline": "February 1, 2027",
        "evidence_url": "https://flairs.test/track",
        "deadline_was_extended": False,
    }
    result = await scout.verify_deadline(event_id=204130)
    assert result.official_url == "https://flairs.test/track"
    assert result.official_url_source == "search"
    assert result.matches_wikicfp is True
    assert any("web search" in warning for warning in result.warnings)
    assert len(gateway.searches) == 1


async def test_search_with_no_plausible_site_raises(scout, gateway):
    gateway.search_hits = [SearchHit(title="Unrelated", url="https://unrelated.test/", snippet="")]
    with pytest.raises(OfficialSiteNotFoundError):
        await scout.verify_deadline(conference_name="NOMS 2027")
    assert gateway.agent_calls == []


async def test_verify_requires_an_argument(scout):
    with pytest.raises(ValueError):
        await scout.verify_deadline()


async def test_repeat_verify_is_cached_and_does_not_spend_again(scout, gateway):
    gateway.pages["2027.ieee-icra.org"] = load("evidence_icra.md")
    gateway.agent_answer = dict(ICRA_ANSWER)
    await scout.verify_deadline(official_url="https://2027.ieee-icra.org")
    await scout.verify_deadline(official_url="https://2027.ieee-icra.org")
    assert len(gateway.agent_calls) == 1


async def test_agent_run_limit_stops_spending(scout, gateway):
    gateway.pages["example"] = "Papers due February 1, 2027."
    gateway.agent_answer = {
        "conference_name": "X",
        "main_paper_deadline": "February 1, 2027",
        "evidence_url": "https://example.test/x",
        "deadline_was_extended": False,
    }
    for index in range(3):
        await scout.verify_deadline(official_url=f"https://example{index}.test/")
    with pytest.raises(AgentBudgetError):
        await scout.verify_deadline(official_url="https://example9.test/")
    assert len(gateway.agent_calls) == 3


def test_tracked_lines_keep_dated_deadline_lines_only():
    lines = extract_tracked_lines(load("evidence_noms.md"))
    assert lines == ["Paper registration & submission: 9 November 2026", "Notification of acceptance: 15 February 2027", "Final Camera Ready papers due: 28 February 2027"]


async def test_watch_detects_an_extension(scout, gateway):
    gateway.monitor_text = load("evidence_noms.md")
    info = await scout.watch_deadline("https://noms2027.ieee-noms.org/authors/call", "NOMS 2027")
    assert info.monitor_id == "mon-1" and len(info.tracked_lines) == 3
    assert "$0.005" in info.note

    unchanged = await scout.check_watch("mon-1")
    assert not unchanged.changed

    gateway.monitor_text = load("evidence_noms.md").replace("9 November 2026", "16 November 2026 (extended)")
    changed = await scout.check_watch("mon-1")
    assert changed.changed
    assert changed.added_lines == ["Paper registration & submission: 16 November 2026 (extended)"]
    assert changed.removed_lines == ["Paper registration & submission: 9 November 2026"]


async def test_stop_watch_deletes_and_forgets(scout, gateway):
    gateway.monitor_text = load("evidence_noms.md")
    await scout.watch_deadline("https://noms2027.ieee-noms.org/authors/call", "NOMS 2027")
    assert (await scout.stop_watch("mon-1")).stopped
    assert gateway.deleted == ["mon-1"]
    with pytest.raises(WatchNotFoundError):
        await scout.check_watch("mon-1")


async def test_stop_watch_refuses_monitors_it_did_not_create(scout, gateway):
    with pytest.raises(WatchNotFoundError):
        await scout.stop_watch("someone-elses-monitor")
    assert gateway.deleted == []


async def test_monitor_deleted_elsewhere_is_reported(scout, gateway):
    gateway.monitor_text = load("evidence_noms.md")
    await scout.watch_deadline("https://noms2027.ieee-noms.org/authors/call", "NOMS 2027")
    gateway.monitor_gone = True
    with pytest.raises(WatchNotFoundError):
        await scout.check_watch("mon-1")
    assert scout.store.get("mon-1") is None


async def test_watch_rejects_non_web_url(scout):
    with pytest.raises(ValueError):
        await scout.watch_deadline("file:///etc/passwd", "X")
