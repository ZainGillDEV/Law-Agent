from datetime import date

from deadline_engine import compute_deadline, parse_date, rule_from_menu_choice


def test_appeal_district_30_days():
    r = compute_deadline("appeal_district", date(2026, 1, 1))
    assert r.deadline == date(2026, 1, 31)


def test_appeal_high_court_90_days():
    r = compute_deadline("appeal_high_court", date(2026, 1, 1))
    assert r.deadline == date(2026, 4, 1)


def test_years_rule():
    r = compute_deadline("possession", date(2020, 6, 15))
    assert r.deadline == date(2032, 6, 15)


def test_leap_day_start():
    r = compute_deadline("money_recovery", date(2024, 2, 29))
    assert r.deadline == date(2027, 2, 27) or r.deadline == date(2027, 3, 1) or r.deadline == date(2027, 2, 28)


def test_sunday_rolls_forward():
    # 2 Jan 2026 + 30 days = 1 Feb 2026 (Sunday) -> 2 Feb
    r = compute_deadline("appeal_district", date(2026, 1, 2))
    assert r.deadline == date(2026, 2, 2)
    assert r.rolled_forward is True


def test_holiday_rolls_forward():
    # 31 Jan holiday, 1 Feb Sunday -> 2 Feb
    r = compute_deadline("appeal_district", date(2026, 1, 1),
                         holidays=frozenset({date(2026, 1, 31)}))
    assert r.deadline == date(2026, 2, 2)


def test_parse_date_formats():
    assert parse_date("12/3/2025") == date(2025, 3, 12)
    assert parse_date("12-03-25") == date(2025, 3, 12)
    assert parse_date("12.3.2025") == date(2025, 3, 12)
    assert parse_date("12 March 2025") == date(2025, 3, 12)
    assert parse_date("12 mar 25") == date(2025, 3, 12)
    assert parse_date("aaj", today=date(2026, 9, 30)) == date(2026, 9, 30)


def test_parse_date_invalid():
    assert parse_date("31/02/2025") is None
    assert parse_date("kuch bhi") is None


def test_menu_choice():
    assert rule_from_menu_choice("1").key == "appeal_district"
    assert rule_from_menu_choice("99") is None
    assert rule_from_menu_choice("abc") is None