"""When a site's layout changes, tools must raise SITE_CHANGED and never return empty or partial data."""

import pytest
from conftest import load

from cfp_scout.errors import SiteChangedError
from cfp_scout.parsers import parse_category_page, parse_event_page, parse_icore_page, parse_title_search


def test_renamed_listing_header_raises():
    html = load("category_robotics.html").replace("<td> Deadline</td>", "<td> Due date</td>")
    html = html.replace("Most Recent", "")
    with pytest.raises(SiteChangedError):
        parse_category_page(html, "robotics")


def test_removed_event_links_raise():
    html = load("category_robotics.html").replace("event.showcfp?eventid=", "event.view?id=")
    with pytest.raises(SiteChangedError):
        parse_category_page(html, "robotics")


def test_extra_cell_in_event_row_raises():
    html = load("category_robotics.html").replace(
        '<td align="left">Chengdu, China</td>', '<td align="left">Chengdu</td><td align="left">China</td>'
    )
    with pytest.raises(SiteChangedError):
        parse_category_page(html, "robotics")


def test_unrecognised_category_page_raises():
    with pytest.raises(SiteChangedError):
        parse_category_page("<html><body><div>A completely new design</div></body></html>", "robotics")


def test_title_search_without_heading_raises():
    html = load("title_search.html").replace("Matched Call For Papers", "Results")
    with pytest.raises(SiteChangedError):
        parse_title_search(html, "embodied robotics")


def test_event_without_field_table_raises():
    html = load("event_flairs.html").replace('class="gglu"', 'class="details"')
    with pytest.raises(SiteChangedError):
        parse_event_page(html, 204130)


def test_event_with_renamed_fields_raises():
    html = load("event_flairs.html").replace("<th>When</th>", "<th>Dates</th>").replace(
        "<th>Submission Deadline</th>", "<th>Papers due</th>"
    )
    with pytest.raises(SiteChangedError):
        parse_event_page(html, 204130)


def test_icore_with_renamed_columns_raises():
    html = load("icore_iros.html").replace("<b>Rank</b>", "<b>Tier</b>")
    with pytest.raises(SiteChangedError):
        parse_icore_page(html, "IROS")


def test_icore_row_with_missing_cells_raises():
    html = load("icore_iros.html").replace("4602", "").replace('<td class="nowrap">\n                                2\n                            </td>', "")
    html = html.replace('<td class="nowrap">\n                                5.0\n                            </td>', "")
    html = html.replace('<td class="nowrap">\n                                \n                            </td>', "")
    with pytest.raises(SiteChangedError):
        parse_icore_page(html, "IROS")


def test_icore_redesign_raises():
    with pytest.raises(SiteChangedError):
        parse_icore_page("<html><body>New portal</body></html>", "IROS")
