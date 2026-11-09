from datetime import date

import pytest

from cfp_scout.dates import date_spellings, find_dates, parse_date, parse_listing_deadline, parse_range


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Nov 5, 2026", date(2026, 11, 5)),
        ("September 16, 2026 (23:59 PST) - extended to this date", date(2026, 9, 16)),
        ("9 November 2026", date(2026, 11, 9)),
        ("1st of February, 2027", date(2027, 2, 1)),
        ("January 31, 2027 (Sun)", date(2027, 1, 31)),
        ("2027-02-01T00:00:00", date(2027, 2, 1)),
        ("Sept 3rd 2026", date(2026, 9, 3)),
        ("N/A", None),
        ("TBD", None),
        (None, None),
        ("31st of April, 2027", None),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_listing_deadline_splits_paper_and_abstract():
    assert parse_listing_deadline("Feb 1, 2027 (Jan 22, 2027)") == (date(2027, 2, 1), date(2027, 1, 22))
    assert parse_listing_deadline("Nov 5, 2026") == (date(2026, 11, 5), None)
    assert parse_listing_deadline("N/A") == (None, None)


def test_range():
    assert parse_range("Dec 4, 2026 - Dec 6, 2026") == (date(2026, 12, 4), date(2026, 12, 6))
    assert parse_range("Dec 4, 2026") == (date(2026, 12, 4), date(2026, 12, 4))
    assert parse_range("N/A") == (None, None)


def test_mixed_formats_keep_page_order():
    assert find_dates("15 February 2027 then Mar 1, 2027 then 2027-04-02") == [
        date(2027, 2, 15),
        date(2027, 3, 1),
        date(2027, 4, 2),
    ]


def test_spellings_cover_real_site_formats():
    assert "1st of february, 2027" in date_spellings(date(2027, 2, 1))
    assert "9 november 2026" in date_spellings(date(2026, 11, 9))
    assert "september 16, 2026" in date_spellings(date(2026, 9, 16))
    assert "sep 16, 2026" in date_spellings(date(2026, 9, 16))
    assert "november 06, 2026" in date_spellings(date(2026, 11, 6))
