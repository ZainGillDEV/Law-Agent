import json
from datetime import date

from case_extractor import parse_llm_case

TODAY = date(2026, 10, 2)

GOOD = {
    "document_type": "Judgment",
    "court": "Senior Civil Judge, Lahore",
    "case_number": "Civil Suit No. 1187 of 2025",
    "case_title": "Muhammad Arslan Tariq vs Kamran Yousaf",
    "decision_date": "18/09/2026",
    "next_hearing_date": "28/10/2026",
    "deadline_question": "Civil appeal against decree of Senior Civil Judge to District Judge",
}


def test_full_case():
    info = parse_llm_case("Here: " + json.dumps(GOOD), today=TODAY)
    assert info["decision_date"] == "2026-09-18"
    assert info["next_hearing_date"] == "2026-10-28"
    assert info["case_title"] == "Muhammad Arslan Tariq vs Kamran Yousaf"
    assert info["court"] == "Senior Civil Judge, Lahore"


def test_bad_dates_dropped_other_fields_kept():
    bad = dict(GOOD, decision_date="18/09/2030", next_hearing_date="01/01/2020")
    info = parse_llm_case(json.dumps(bad), today=TODAY)
    assert "decision_date" not in info       # future decision
    assert "next_hearing_date" not in info   # hearing already passed
    assert info["court"] == "Senior Civil Judge, Lahore"


def test_nulls_and_placeholders():
    info = parse_llm_case(json.dumps(dict(GOOD, court=None, case_number="Not mentioned")), today=TODAY)
    assert "court" not in info and "case_number" not in info


def test_garbage():
    assert parse_llm_case("no json", today=TODAY) is None
    assert parse_llm_case('{"court": null}', today=TODAY) is None
    assert parse_llm_case("[1, 2]", today=TODAY) is None


def test_long_text_truncated():
    info = parse_llm_case(json.dumps(dict(GOOD, case_title="A" * 500)), today=TODAY)
    assert len(info["case_title"]) == 100
