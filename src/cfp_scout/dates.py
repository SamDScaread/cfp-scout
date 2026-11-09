"""Turn the date formats found on WikiCFP and conference sites into ISO dates."""

from __future__ import annotations

import re
from datetime import date

_MONTHS = {
    name: index
    for index, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
# "Sep 16, 2026", "September 16th 2026"
_MDY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
# "9 November 2026", "1st of February, 2027"
_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?,?\s+(\d{{4}})\b", re.I)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_dates(text: str) -> list[date]:
    """Return every recognisable date in text, in the order it appears."""
    if not text:
        return []
    found: list[tuple[int, date]] = []
    for match in _ISO.finditer(text):
        parsed = _safe_date(int(match[1]), int(match[2]), int(match[3]))
        if parsed:
            found.append((match.start(), parsed))
    for match in _MDY.finditer(text):
        parsed = _safe_date(int(match[3]), _MONTHS[match[1].lower()], int(match[2]))
        if parsed:
            found.append((match.start(), parsed))
    for match in _DMY.finditer(text):
        parsed = _safe_date(int(match[3]), _MONTHS[match[2].lower()], int(match[1]))
        if parsed:
            found.append((match.start(), parsed))
    return [item for _, item in sorted(found, key=lambda pair: pair[0])]


def parse_date(text: str | None) -> date | None:
    """Return the first date in text, or None for values like 'N/A' and 'TBD'."""
    dates = find_dates(text or "")
    return dates[0] if dates else None


def iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def parse_range(text: str | None) -> tuple[date | None, date | None]:
    """Parse 'Dec 4, 2026 - Dec 6, 2026'. A single date is both start and end."""
    dates = find_dates(text or "")
    if not dates:
        return None, None
    return dates[0], dates[1] if len(dates) > 1 else dates[0]


def parse_listing_deadline(text: str | None) -> tuple[date | None, date | None]:
    """Parse a WikiCFP listing deadline. 'Feb 1, 2027 (Jan 22, 2027)' is (paper, abstract)."""
    dates = find_dates(text or "")
    if not dates:
        return None, None
    return dates[0], dates[1] if len(dates) > 1 else None


def date_spellings(value: date) -> list[str]:
    """Common ways a site may write a date, lowercased, used to re-find it on a page."""
    month_names = [name for name, number in _MONTHS.items() if number == value.month]
    day = value.day
    ordinal = f"{day}{_ordinal_suffix(day)}"
    spellings = [value.isoformat()]
    for month in month_names:
        spellings += [
            f"{month} {day}, {value.year}",
            f"{month} {day} {value.year}",
            f"{month} {ordinal}, {value.year}",
            f"{month} {ordinal} {value.year}",
            f"{day} {month} {value.year}",
            f"{day} {month}, {value.year}",
            f"{ordinal} {month} {value.year}",
            f"{ordinal} of {month}, {value.year}",
            f"{ordinal} of {month} {value.year}",
        ]
        if day < 10:
            spellings += [
                f"{month} 0{day}, {value.year}",
                f"0{day} {month} {value.year}",
            ]
    return spellings


def _ordinal_suffix(day: int) -> str:
    if 11 <= day <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
