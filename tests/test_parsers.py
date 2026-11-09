import pytest
from conftest import load

from cfp_scout.errors import EventNotFoundError
from cfp_scout.parsers import parse_category_page, parse_event_page, parse_icore_page, parse_title_search


def test_category_page_returns_typed_calls():
    page = parse_category_page(load("category_robotics.html"), "robotics")
    assert page.found and page.total == 3237 and page.pages == 162
    first = page.calls[0]
    assert first.event_id == 190921
    assert first.acronym == "AISRA 2026"
    assert first.title == "2026 International Conference on Embodied AI and Robotics"
    assert (first.start_date, first.end_date) == ("2026-12-04", "2026-12-06")
    assert first.location == "Chengdu, China"
    assert first.submission_deadline == "2026-11-05"
    assert first.abstract_deadline is None
    assert first.wikicfp_url.endswith("eventid=190921")


def test_journal_row_with_na_dates_has_nulls():
    call = parse_category_page(load("category_robotics.html"), "robotics").calls[1]
    assert (call.start_date, call.end_date, call.location) == (None, None, None)
    assert call.submission_deadline == "2026-11-06"


def test_parenthesised_date_is_abstract_deadline():
    call = parse_category_page(load("category_robotics.html"), "robotics").calls[2]
    assert call.acronym == "SOEA 2027"
    assert call.submission_deadline == "2027-03-07"
    assert call.abstract_deadline == "2027-02-20"


def test_unknown_category_is_not_found_rather_than_broken():
    page = parse_category_page(load("category_unknown_redirects_home.html"), "zzz")
    assert not page.found and page.calls == []


def test_title_search():
    page = parse_title_search(load("title_search.html"), "embodied robotics")
    assert [call.event_id for call in page.calls] == [203402, 203297, 194768]
    assert page.calls[0].abstract_deadline == "2027-01-22"
    assert page.related_categories == ["embodied ai", "robotics", "field robotics"]


def test_event_page_fields():
    detail = parse_event_page(load("event_flairs.html"), 204130)
    assert detail.acronym == "DGAI-FLAIRS 2027"
    assert detail.title == "FLAIRS-40 Special Track: Deliberative and Generative AI Hybrids and Foundations"
    assert (detail.start_date, detail.end_date) == ("2027-05-24", "2027-05-27")
    assert detail.location == "St. Pete Beach, Florida"
    assert detail.abstract_deadline == "2027-01-22"
    assert detail.submission_deadline == "2027-02-01"
    assert detail.notification_due == "2027-03-09"
    assert detail.final_version_due == "2027-04-05"
    assert detail.categories == ["AI", "NLP", "ML"]
    assert detail.official_url == "https://example.org/flairs-special-track/"


def test_event_date_lines_keep_deadlines_and_drop_personal_data():
    lines = parse_event_page(load("event_flairs.html"), 204130).date_lines
    assert lines == ["Abstracts are due January 22, 2027.", "Technical papers - 9 Nov 2026"]


def test_missing_event_is_reported_as_not_found():
    with pytest.raises(EventNotFoundError):
        parse_event_page(load("category_unknown_redirects_home.html"), 999)


def test_icore_rank_row():
    ranks = parse_icore_page(load("icore_iros.html"), "IROS").ranks
    assert len(ranks) == 1
    assert (ranks[0].acronym, ranks[0].rank, ranks[0].source, ranks[0].field_of_research) == (
        "IROS",
        "A",
        "ICORE2026",
        "4602",
    )


def test_icore_empty_result_is_a_real_empty():
    assert parse_icore_page(load("icore_empty.html"), "NOTAVENUEXYZ").ranks == []
