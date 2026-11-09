from conftest import load

from cfp_scout import health
from cfp_scout.health import run_health_check
from cfp_scout.service import CfpScout


def healthy_pages(gateway):
    gateway.pages["call?conference=robotics"] = load("category_robotics.html")
    gateway.pages["eventid=190921"] = load("event_flairs.html")
    gateway.pages["tool.search?q=robotics"] = load("title_search.html")
    gateway.pages["search=ICRA"] = load("icore_iros.html").replace("IROS", "ICRA")
    gateway.pages["search=NOTAVENUEXYZ"] = load("icore_empty.html")


async def test_healthy_when_every_site_parses(scout, gateway):
    healthy_pages(gateway)
    report = await run_health_check(scout)
    assert report.ok, report
    assert [check.name for check in report.checks] == [
        "wikicfp_category_page",
        "wikicfp_event_page",
        "wikicfp_title_search",
        "icore_rank_lookup",
        "icore_empty_result",
    ]


async def test_layout_change_turns_the_report_red_and_names_the_check(scout, gateway):
    healthy_pages(gateway)
    gateway.pages["call?conference=robotics"] = load("category_robotics.html").replace("<td> Deadline</td>", "<td> Due</td>")
    report = await run_health_check(scout)
    assert not report.ok
    failed = {check.name: check.detail for check in report.checks if not check.ok}
    assert "SITE_CHANGED" in failed["wikicfp_category_page"]
    assert "Skipped" in failed["wikicfp_event_page"]
    assert "icore_rank_lookup" not in failed


async def test_icore_rank_disappearing_is_caught(scout, gateway):
    healthy_pages(gateway)
    gateway.pages["search=ICRA"] = load("icore_empty.html")
    report = await run_health_check(scout)
    assert not report.ok
    assert any(check.name == "icore_rank_lookup" and not check.ok for check in report.checks)


async def test_health_reads_fresh_pages_not_the_cache(scout, gateway):
    healthy_pages(gateway)
    await run_health_check(scout)
    first = len(gateway.fetches)
    await run_health_check(scout)
    assert len(gateway.fetches) == first * 2


async def test_agent_probe_only_runs_when_asked(scout, gateway):
    healthy_pages(gateway)
    gateway.pages["2027.ieee-icra.org"] = load("evidence_icra.md")
    gateway.agent_answer = {
        "conference_name": "ICRA 2027",
        "main_paper_deadline": "September 16, 2026",
        "evidence_url": "https://2027.ieee-icra.org/contribute/call/",
        "deadline_was_extended": True,
    }
    await run_health_check(scout)
    assert gateway.agent_calls == []
    report = await run_health_check(scout, include_agent=True)
    assert report.ok and len(gateway.agent_calls) == 1


ICRA_LINES = "* Paper submission deadline: **September 16, 2026 (23:59 PST)**\n* Notification: **January 31, 2027**"


async def test_watch_probe_creates_runs_and_always_deletes(scout, gateway):
    healthy_pages(gateway)
    gateway.monitor_text = ICRA_LINES
    report = await run_health_check(scout, include_watch=True)
    assert report.ok, report
    assert report.checks[-1].name == "monitor_watch_cycle"
    assert gateway.deleted == ["mon-1"] and scout.store.get("mon-1") is None
    assert gateway.agent_calls == []


async def test_watch_probe_fails_loudly_and_still_deletes(scout, gateway):
    healthy_pages(gateway)
    gateway.monitor_text = ICRA_LINES
    gateway.monitor_gone = True  # The run endpoint loses the monitor.
    report = await run_health_check(scout, include_watch=True)
    assert not report.ok
    failed = {check.name: check.detail for check in report.checks if not check.ok}
    assert "WATCH_NOT_FOUND" in failed["monitor_watch_cycle"] and "no longer exists" in failed["monitor_watch_cycle"]
    assert scout.store.get("mon-1") is None


def test_cli_exits_2_without_key(monkeypatch, capsys):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    assert health.main([]) == 2
    assert "TINYFISH_API_KEY" in capsys.readouterr().err


def test_cli_exits_1_and_prints_fail_when_broken(monkeypatch, capsys):
    from cfp_scout.models import HealthCheckItem, HealthReport

    async def fake(include_agent, include_watch):
        return HealthReport(
            ok=False,
            checked_at="2026-11-04T00:00:00+00:00",
            checks=[HealthCheckItem(name="wikicfp_category_page", ok=False, detail="[SITE_CHANGED] x", duration_ms=1)],
        )

    monkeypatch.setattr(health, "_run_cli", fake)
    assert health.main([]) == 1
    output = capsys.readouterr().out
    assert "FAIL  wikicfp_category_page" in output and "BROKEN" in output
