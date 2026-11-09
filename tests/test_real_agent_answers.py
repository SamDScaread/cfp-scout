"""Replays of real TinyFish Agent answers captured on 2026-11-04, checked against real pages."""

from conftest import load
from mcp import Client


async def test_icrai_deadline_in_a_sidebar_is_verified(scout, gateway):
    """Cleaned markdown dropped this sidebar during testing, so the full body must be read."""
    gateway.pages["icrai.org"] = load("evidence_icrai_sidebar.html")
    gateway.agent_answer = {
        "conference_name": "ICRAI 2026",
        "deadline_quote": "Submission Deadline:\nNovember 05, 2026",
        "deadline_was_extended": False,
        "evidence_url": "https://icrai.org/index.html",
        "main_paper_deadline": "November 05, 2026",
        "notification_date": "November 20, 2026",
        "timezone": "Asia/Seoul (KST)",
    }
    gateway.agent_steps = 11
    result = await scout.verify_deadline(official_url="https://icrai.org/", conference_name="ICRAI 2026")
    assert (result.status, result.verification_method) == ("verified", "quote_match")
    assert result.deadline == "2026-11-05"
    assert result.notification_date == "2026-11-20"
    assert result.was_extended is False
    assert result.submissions_closed is False
    assert result.estimated_cost_usd == 0.176
    assert result.timezone is None  # The Agent said KST, but the page never states a timezone.


async def test_icra_reworded_quote_falls_back_to_the_date_on_the_page(scout, gateway):
    """The Agent paraphrased instead of quoting, so a quote match must fail and the date must carry it."""
    gateway.pages["2027.ieee-icra.org"] = load("evidence_icra.md")
    gateway.agent_answer = {
        "conference_name": "ICRA 2027",
        "deadline_quote": "The main full paper submission deadline was September 16, 2026 (23:59 PST). There is no plan to extend the paper submission deadline.",
        "deadline_was_extended": True,
        "evidence_url": "https://2027.ieee-icra.org/contribute/call-for-icra-2027-papers-now-accepting-submissions/",
        "main_paper_deadline": "September 16, 2026 (23:59 PST) (extended from the original deadline)",
        "notification_date": "Notification of acceptance/rejection on January 31, 2027",
        "timezone": "PST",
    }
    result = await scout.verify_deadline(official_url="https://2027.ieee-icra.org", conference_name="ICRA 2027")
    assert (result.status, result.verification_method) == ("verified", "date_match")
    assert result.deadline == "2026-09-16"
    assert result.was_extended is True
    assert result.submissions_closed is True
    assert result.notification_date == "2027-01-31"
    assert result.timezone == "PST"


async def test_noms_and_xai_answers_keep_only_fields_found_on_the_page(scout, gateway):
    gateway.pages["xaiworldconference.com"] = load("evidence_xai.md")
    gateway.agent_answer = {
        "conference_name": "XAI World Conference 2027",
        "main_paper_deadline": "1st of February, 2027",
        "notification_date": "9th of March, 2027",
        "evidence_url": "https://xaiworldconference.com/2027/important-dates/",
        "timezone": "Anywhere on Earth (AoE)",
        "deadline_was_extended": False,
    }
    result = await scout.verify_deadline(official_url="https://xaiworldconference.com/2027/")
    assert result.deadline == "2027-02-01"
    assert result.timezone == "Anywhere on Earth (AoE)"  # The page words it slightly differently.
    assert result.notification_date is None


async def test_server_starts_over_stdio_and_lists_tools(monkeypatch, tmp_path):
    """Starts the real entry point as a subprocess, the way an MCP client does. No key is needed to list tools."""
    import sys

    from mcp import StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cfp_scout.server"],
        env={"CFP_SCOUT_HOME": str(tmp_path), "PATH": ""},
    )
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
    assert len(tools) == 8
