from datetime import date

from deadline_engine import ARTICLES, compute_deadline, get_article, parse_date


# ---------- Data checks ----------
def test_articles_loaded():
    assert len(ARTICLES) > 170


def test_omitted_articles_not_present():
    for omitted in ["4", "45", "46", "133", "144", "150A", "162A", "182"]:
        assert get_article(omitted) is None


def test_every_article_has_exactly_one_period():
    for a in ARTICLES.values():
        assert sum(1 for v in (a.years, a.months, a.days) if v) == 1, a.article


def test_get_article_formats():
    assert get_article("152").article == "152"
    assert get_article("art 152").article == "152"
    assert get_article("Article 11A").article == "11A"
    assert get_article("art. 64a").article == "64A"
    assert get_article("999") is None


def test_flagged_articles():
    assert get_article("154").needs_review is True
    assert get_article("152").needs_review is False


# ---------- Deadlines ----------
def test_art_152_district_appeal_30_days():
    assert compute_deadline("152", date(2026, 1, 1)).deadline == date(2026, 1, 31)


def test_art_156_high_court_appeal_90_days():
    assert compute_deadline("156", date(2026, 1, 1)).deadline == date(2026, 4, 1)


def test_art_142_possession_12_years():
    assert compute_deadline("142", date(2020, 6, 15)).deadline == date(2032, 6, 15)


def test_art_159_leave_to_defend_10_days():
    # 1 Oct 2026 (Thu) + 10 days = 11 Oct 2026 (Sun) -> 12 Oct
    r = compute_deadline("159", date(2026, 10, 1))
    assert r.deadline == date(2026, 10, 12)
    assert r.rolled_forward is True


def test_art_3_six_months_month_end():
    # 31 Aug + 6 months -> 28 Feb (no 31 Feb); 28 Feb 2027 is a Sunday -> 1 Mar
    assert compute_deadline("3", date(2026, 8, 31)).deadline == date(2027, 3, 1)


def test_holiday_rolls_forward():
    r = compute_deadline("152", date(2026, 1, 1), holidays=frozenset({date(2026, 1, 31)}))
    assert r.deadline == date(2026, 2, 2)  # 31 Jan holiday, 1 Feb Sunday -> 2 Feb


def test_citation():
    assert compute_deadline("152", date(2026, 1, 1)).article.citation == \
        "Limitation Act 1908, First Schedule, Art. 152"


# ---------- Dates ----------
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


# ---------- Sec. 12(2): certified copy ----------
def test_copy_days_added_for_appeal():
    # Decree 18 Sep 2026 + 30 = 18 Oct; copy applied 20 Sep, received 30 Sep -> +10 = 28 Oct (Wed)
    r = compute_deadline("152", date(2026, 9, 18),
                         copy_applied=date(2026, 9, 20), copy_received=date(2026, 9, 30))
    assert r.excluded_days == 10 and r.copy_status == "added"
    assert r.deadline == date(2026, 10, 28)


def test_copy_not_given_for_appeal():
    r = compute_deadline("152", date(2026, 9, 18))
    assert r.copy_status == "not_given"
    assert r.deadline == date(2026, 10, 19)  # 18 Oct is Sunday


def test_copy_applied_after_period_is_ignored():
    r = compute_deadline("152", date(2026, 8, 1),
                         copy_applied=date(2026, 9, 10), copy_received=date(2026, 9, 20))
    assert r.copy_status == "late" and r.excluded_days == 0


def test_copy_pending():
    r = compute_deadline("156", date(2026, 9, 1), copy_applied=date(2026, 9, 5), copy_pending=True)
    assert r.copy_status == "pending" and r.excluded_days == 0


def test_copy_time_ignored_for_suits():
    r = compute_deadline("57", date(2024, 3, 5),
                         copy_applied=date(2024, 3, 6), copy_received=date(2024, 3, 20))
    assert r.copy_status == "n/a" and r.excluded_days == 0


def test_review_application_gets_copy_time():
    assert get_article("173").copy_time_excluded is True
    assert get_article("164").copy_time_excluded is False
