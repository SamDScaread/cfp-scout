"""Parse WikiCFP and ICORE pages returned by TinyFish Fetch.

Every parser separates two cases that must never be confused:
a real empty result, and a page whose structure changed. The second raises
SiteChangedError, which is what makes these tools break loudly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from .dates import find_dates, iso, parse_date, parse_listing_deadline, parse_range
from .errors import EventNotFoundError, SiteChangedError
from .models import CallDetail, CallSummary, VenueRank

WIKICFP_BASE = "http://www.wikicfp.com"
_EVENT_ID = re.compile(r"eventid=(\d+)")
_TOTAL = re.compile(r"Total of\s+([\d,]+)\s+CFPs?\s+in\s+([\d,]+)\s+pages?", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_MAX_DATE_LINES = 25


def event_url(event_id: int) -> str:
    return f"{WIKICFP_BASE}/cfp/servlet/event.showcfp?eventid={event_id}"


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _optional(text: str | None) -> str | None:
    value = _clean(text)
    return None if value.upper() in {"", "N/A", "TBD", "NULL"} else value


def _find_listing_table(soup: BeautifulSoup) -> Tag | None:
    for table in soup.find_all("table"):
        first_row = table.find("tr")
        if first_row is None:
            continue
        cells = [_clean(cell.get_text()) for cell in first_row.find_all("td", recursive=False)]
        if cells[:4] == ["Event", "When", "Where", "Deadline"]:
            return table
    return None


def _table_rows(table: Tag) -> list[Tag]:
    body = table.find("tbody", recursive=False)
    return (body or table).find_all("tr", recursive=False)


def _parse_rows(table: Tag, page_label: str) -> list[CallSummary]:
    rows = _table_rows(table)[1:]
    if len(rows) % 2:
        raise SiteChangedError(
            f"{page_label}: expected two table rows per event but found an odd number ({len(rows)}).",
            hint="Run health_check, then update parsers.py for the new layout.",
        )
    calls: list[CallSummary] = []
    for first, second in zip(rows[0::2], rows[1::2]):
        link = first.find("a", href=_EVENT_ID)
        top_cells = first.find_all("td", recursive=False)
        bottom_cells = second.find_all("td", recursive=False)
        if link is None or len(top_cells) < 2 or len(bottom_cells) != 3:
            raise SiteChangedError(
                f"{page_label}: an event row no longer has the expected link and When, Where, Deadline cells.",
                hint="Run health_check, then update parsers.py for the new layout.",
            )
        event_id = int(_EVENT_ID.search(link["href"]).group(1))
        start, end = parse_range(bottom_cells[0].get_text())
        paper, abstract = parse_listing_deadline(bottom_cells[2].get_text())
        calls.append(
            CallSummary(
                event_id=event_id,
                acronym=_clean(link.get_text()),
                title=_clean(top_cells[1].get_text()),
                start_date=iso(start),
                end_date=iso(end),
                location=_optional(bottom_cells[1].get_text()),
                submission_deadline=iso(paper),
                abstract_deadline=iso(abstract),
                wikicfp_url=event_url(event_id),
            )
        )
    return calls


@dataclass
class CategoryPage:
    found: bool
    calls: list[CallSummary]
    total: int | None
    pages: int | None


def parse_category_page(html: str, category: str) -> CategoryPage:
    """Parse /cfp/call?conference=<category>. Unknown categories redirect to the home page."""
    soup = BeautifulSoup(html, "html.parser")
    table = _find_listing_table(soup)
    if table is None:
        if soup.find(string=re.compile(r"Most Recent Calls For Papers|Welcome!")):
            return CategoryPage(found=False, calls=[], total=None, pages=None)
        raise SiteChangedError(
            f"WikiCFP category page for '{category}' has neither a results table nor the home page content.",
            hint="Run health_check, then update parsers.py for the new layout.",
        )
    total_match = _TOTAL.search(soup.get_text(" "))
    total = int(total_match[1].replace(",", "")) if total_match else None
    pages = int(total_match[2].replace(",", "")) if total_match else None
    return CategoryPage(
        found=True,
        calls=_parse_rows(table, f"WikiCFP category '{category}'"),
        total=total,
        pages=pages,
    )


@dataclass
class TitleSearchPage:
    calls: list[CallSummary]
    related_categories: list[str]


def parse_title_search(html: str, query: str) -> TitleSearchPage:
    """Parse /cfp/servlet/tool.search. The 'Matched' headings prove this is the results page."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.find(string=re.compile(r"Matched Call For Papers")) is None:
        raise SiteChangedError(
            f"WikiCFP search page for '{query}' no longer has its 'Matched Call For Papers' heading.",
            hint="Run health_check, then update parsers.py for the new layout.",
        )
    related: list[str] = []
    for link in soup.find_all("a", href=re.compile(r"/cfp/call\?conference=")):
        name = _clean(link.get_text())
        if name and link.find_parent("h3") and name not in related:
            related.append(name)
    table = _find_listing_table(soup)
    calls = _parse_rows(table, f"WikiCFP search '{query}'") if table is not None else []
    return TitleSearchPage(calls=calls, related_categories=related)


def _property_content(soup: BeautifulSoup, prop: str) -> str | None:
    node = soup.find(attrs={"property": prop})
    if node is None:
        return None
    return node.get("content") or _clean(node.get_text()) or None


def _field_table(soup: BeautifulSoup) -> dict[str, str]:
    fields: dict[str, str] = {}
    for table in soup.find_all("table", class_="gglu"):
        for row in table.find_all("tr"):
            header = row.find("th")
            value = row.find("td")
            if header is None or value is None:
                continue
            marked = value.find(attrs={"property": "v:startDate"})
            fields[_clean(header.get_text())] = (
                marked.get("content", "") if marked is not None else _clean(value.get_text())
            )
    return fields


def _date_lines(soup: BeautifulSoup) -> list[str]:
    body = soup.find("div", class_="cfp")
    if body is None:
        return []
    for br in body.find_all("br"):
        br.replace_with("\n")
    lines: list[str] = []
    for raw in body.get_text().splitlines():
        line = _clean(raw)
        # Email addresses and "Contact: name" lines are personal data, not deadlines.
        if not line or _EMAIL.search(line) or line.lower().startswith("contact"):
            continue
        if find_dates(line) and line not in lines:
            lines.append(line[:240])
        if len(lines) >= _MAX_DATE_LINES:
            break
    return lines


def parse_event_page(html: str, event_id: int, page_title: str | None = None) -> CallDetail:
    soup = BeautifulSoup(html, "html.parser")
    fields = _field_table(soup)
    acronym = _property_content(soup, "dc:title") or _property_content(soup, "v:summary")
    if not fields or not acronym:
        if soup.find(string=re.compile(r"Most Recent Calls For Papers|Welcome!")) or not soup.get_text(strip=True):
            raise EventNotFoundError(
                f"WikiCFP has no event {event_id}.",
                hint="Use an event_id returned by search_calls.",
            )
        raise SiteChangedError(
            f"WikiCFP event {event_id} no longer has its field table or title metadata.",
            hint="Run health_check, then update parsers.py for the new layout.",
        )
    if "Submission Deadline" not in fields and "When" not in fields:
        raise SiteChangedError(
            f"WikiCFP event {event_id} has none of the expected When or Submission Deadline fields.",
            hint="Run health_check, then update parsers.py for the new layout.",
        )
    acronym = _clean(acronym)
    title = _clean(_property_content(soup, "dc:description"))
    if not title and page_title and ":" in page_title:
        title = _clean(page_title.split(":", 1)[1])
    start, end = parse_range(fields.get("When"))
    categories: list[str] = []
    for link in soup.find_all("a", href=re.compile(r"call\?conference=")):
        name = _clean(link.get_text())
        if name and link.find_parent("h5") and name not in categories:
            categories.append(name)
    official = _property_content(soup, "dc:source")
    if not official:
        link = soup.find("a", target="_newtab")
        official = link.get("href") if link is not None else None
    if official and not official.lower().startswith(("http://", "https://")):
        official = None
    return CallDetail(
        event_id=event_id,
        acronym=acronym,
        title=title or acronym,
        start_date=iso(start),
        end_date=iso(end),
        location=_optional(fields.get("Where")),
        abstract_deadline=iso(parse_date(fields.get("Abstract Registration Due"))),
        submission_deadline=iso(parse_date(fields.get("Submission Deadline"))),
        notification_due=iso(parse_date(fields.get("Notification Due"))),
        final_version_due=iso(parse_date(fields.get("Final Version Due"))),
        categories=categories,
        official_url=official,
        date_lines=_date_lines(soup),
        wikicfp_url=event_url(event_id),
    )


@dataclass
class RankPage:
    ranks: list[VenueRank]


def parse_icore_page(html: str, query: str) -> RankPage:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ")
    expected = ["Title", "Acronym", "Source", "Rank"]
    for table in soup.find_all("table"):
        first_row = table.find("tr")
        if first_row is None:
            continue
        headers = [_clean(cell.get_text()) for cell in first_row.find_all("th")]
        if headers[:4] != expected:
            continue
        ranks: list[VenueRank] = []
        for row in table.find_all("tr")[1:]:
            cells = [_clean(cell.get_text()) for cell in row.find_all("td", recursive=False)]
            if len(cells) < 7:
                raise SiteChangedError(
                    f"ICORE result row for '{query}' has {len(cells)} cells, expected at least 7.",
                    hint="Run health_check, then update parsers.py for the new layout.",
                )
            ranks.append(
                VenueRank(
                    title=cells[0],
                    acronym=cells[1],
                    source=cells[2],
                    rank=cells[3],
                    field_of_research=cells[6] or None,
                )
            )
        return RankPage(ranks=ranks)
    if re.search(r"\b0 Results found", text):
        return RankPage(ranks=[])
    raise SiteChangedError(
        f"ICORE page for '{query}' has neither a results table nor '0 Results found'.",
        hint="Run health_check, then update parsers.py for the new layout.",
    )
