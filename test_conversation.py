"""
End-to-end test of the WhatsApp 'add case' flow with a fake database and fake LLM.
No Supabase, WhatsApp or Groq needed.
"""
import sys
import types
from datetime import date, timedelta

# ---------- Fake db module ----------
_sessions: dict = {}
_cases: list = []
_lawyers: dict = {}

fake_db = types.ModuleType("db")
fake_db.get_lawyer = lambda phone: _lawyers.get(phone)
fake_db.update_lawyer = lambda phone, fields: _lawyers.setdefault(phone, {}).update(fields)
fake_db.accept_terms = lambda phone: _lawyers.setdefault(phone, {}).update({"accepted_at": "now"})
fake_db.get_session = lambda phone: _sessions.get(phone, ("idle", {}))
fake_db.set_session = lambda phone, step, draft=None: _sessions.__setitem__(phone, (step, draft or {}))
fake_db.insert_case = lambda row: _cases.append({**row, "case_id": f"c{len(_cases)+1}"}) or _cases[-1]
fake_db.list_active_cases = lambda phone: [c for c in _cases if c["lawyer_phone"] == phone]
fake_db.update_hearing = lambda *a: None
_links: list = []
fake_db.link_file_to_case = lambda phone, file_id, case_id: _links.append((file_id, case_id))
sys.modules["db"] = fake_db

# ---------- Fake LLM ----------
fake_llm = types.ModuleType("llm_client")
fake_llm.chat = lambda system, user, **kw: '{"articles": ["152", "156"]}'
sys.modules["llm_client"] = fake_llm

from conversation_graph import handle_text, offer_case_from_pdf  # noqa: E402

PHONE = "923000000000"


def say(text):
    return "\n".join(handle_text(PHONE, text))


def setup_function():
    _sessions.clear()
    _cases.clear()
    _lawyers.clear()
    _links.clear()
    _lawyers[PHONE] = {"name": "Adv. Test", "accepted_at": "earlier"}  # already onboarded
    sys.modules["llm_client"] = fake_llm  # other test files may have swapped it


# ---------- Onboarding ----------
NEW = "923111111111"


def new_says(text):
    return "\n".join(handle_text(NEW, text))


def test_onboarding_full_flow():
    _lawyers[NEW] = {"name": "WhatsApp Name", "accepted_at": None}
    assert "poora naam" in new_says("hi")
    assert "shehar" in new_says("Adv. Zain Ali")
    assert "Privacy policy" in new_says("lahore")
    reply = new_says("1")
    assert "Shukriya Adv. Zain Ali" in reply and "LawAiAgent Menu" in reply
    assert _lawyers[NEW] == {"name": "Adv. Zain Ali", "city": "Lahore", "accepted_at": "now"}
    assert _sessions[NEW][0] == "idle"


def test_onboarding_blocks_menu_and_cases():
    _lawyers[NEW] = {"accepted_at": None}
    new_says("hi")
    assert "poora naam" in new_says("menu")      # menu cannot skip onboarding
    assert "poora naam" in new_says("1")         # "1" is not a name
    new_says("Adv. Zain Ali")
    new_says("Lahore")
    assert "manzoori" in new_says("cancel")     # must accept
    assert _lawyers[NEW].get("accepted_at") is None


def test_existing_lawyer_without_consent_is_onboarded():
    _lawyers[NEW] = {"name": "Old User", "accepted_at": None}
    _sessions[NEW] = ("idle", {})
    assert "poora naam" in new_says("1")         # wants to add case, onboarding first
    assert _sessions[NEW][0] == "onboard_name"


def test_add_case_with_ai_suggestion():
    decree = date.today() - timedelta(days=10)
    assert "tafseel" in say("1")
    reply = say("Civil judge ke decree ke khilaf District Judge ko appeal")
    assert "Art. 152" in reply and "Art. 156" in reply
    assert "Art. 152" in say("1")             # lawyer confirms suggestion 1
    assert "date of the decree" in say("Ali vs Ahmed").lower()
    say(decree.strftime("%d/%m/%Y"))
    say("skip")                                # no certified-copy dates
    say("Civil Court Lahore")
    say("skip")
    reply = say("1")
    assert "Case saved" in reply
    assert _cases[0]["limitation_citation"] == "Limitation Act 1908, First Schedule, Art. 152"
    assert _cases[0]["limitation_deadline"] >= (decree + timedelta(days=30)).isoformat()


def test_add_case_with_article_number():
    say("1")
    assert "Art. 57" in say("art 57")
    assert _sessions[PHONE][0] == "awaiting_title"


def test_single_digit_is_not_an_article():
    say("1")
    say("1")  # old menu habit: must NOT pick Art. 1
    assert _sessions[PHONE][0] == "awaiting_case_desc"


def test_other_path_has_no_deadline():
    say("1")
    say("other")
    say("489-F")
    say("State vs X")
    say((date.today() - timedelta(days=30)).strftime("%d/%m/%Y"))
    say("Magistrate Court Lahore")
    say("skip")
    reply = say("1")
    assert "limitation date calculate nahi hui" in reply
    assert "limitation_deadline" not in _cases[0]


def test_menu_escapes_any_step():
    say("1")
    say("Civil judge ke decree ke khilaf appeal")
    assert "LawAiAgent Menu" in say("menu")
    assert _sessions[PHONE][0] == "idle"


# ---------- Sec. 12(2) in the conversation ----------
def test_appeal_asks_copy_dates_and_adds_them():
    say("1")
    say("art 152")
    say("Kamran vs Arslan")
    assert "Certified copy" in say("18/09/2026")
    assert "kis date ko mili" in say("20/09/2026")
    assert "10 din" in say("30/09/2026")
    say("District Judge Lahore")
    assert "Certified copy: apply" in say("skip")
    reply = say("1")
    assert "28 Oct 2026" in reply and "10 din shamil" in reply
    assert _cases[0]["copy_received_date"] == "2026-09-30"


def test_appeal_copy_skip():
    say("1")
    say("art 152")
    say("Test")
    say("18/09/2026")
    assert "Court ka naam" in say("skip")
    say("Court")
    say("skip")
    assert "19 Oct 2026" in say("1")


def test_suit_does_not_ask_copy_dates():
    say("1")
    say("art 57")
    say("Loan case")
    assert "Court ka naam" in say("05/03/2024")


# ---------- PDF -> full case ----------
PDF_INFO = {
    "document_type": "Judgment",
    "court": "Senior Civil Judge, Lahore",
    "case_number": "Civil Suit No. 1187 of 2025",
    "case_title": "Muhammad Arslan Tariq vs Kamran Yousaf",
    "decision_date": "2026-09-18",
    "next_hearing_date": "2026-10-28",
    "deadline_question": "Civil appeal against decree of Senior Civil Judge to District Judge",
}


def _card():
    _sessions[PHONE] = ("idle", {})
    return offer_case_from_pdf(PHONE, "file-9", PDF_INFO)


def test_pdf_card_shows_details_and_articles():
    card = _card()
    assert "Muhammad Arslan Tariq vs Kamran Yousaf" in card
    assert "18 Sep 2026 (Friday)" in card and "28 Oct 2026" in card
    assert "Art. 152" in card                   # fake LLM suggests 152 and 156


def test_pdf_case_one_tap_with_copy_dates():
    _card()
    assert "Certified copy" in say("1")          # pick Art. 152 -> appeal -> copy question
    say("20/09/2026")
    reply = say("30/09/2026")                    # saved straight away, no court/hearing questions
    assert "Case saved" in reply and "28 Oct 2026" in reply
    c = _cases[0]
    assert c["title"] == "Muhammad Arslan Tariq vs Kamran Yousaf"
    assert c["court"] == "Senior Civil Judge, Lahore"
    assert c["case_number"] == "Civil Suit No. 1187 of 2025"
    assert c["filing_date"] == "2026-09-18"
    assert c["next_hearing_date"] == "2026-10-28"
    assert c["limitation_citation"].endswith("Art. 152")
    assert _links == [("file-9", "c1")]
    assert _sessions[PHONE][0] == "idle"


def test_pdf_case_without_deadline():
    _card()
    reply = say("0")
    assert "Case saved" in reply and "limitation date calculate nahi hui" in reply
    assert "limitation_deadline" not in _cases[0]
    assert _cases[0]["next_hearing_date"] == "2026-10-28"


def test_pdf_case_suit_article_saves_immediately():
    _card()
    reply = say("art 120")                       # not an appeal -> no copy question
    assert "Case saved" in reply


def test_pdf_case_edit_falls_back_to_manual():
    _card()
    assert "tafseel" in say("edit")
    say("art 152")
    assert "PDF ke mutabiq" in say("My title")


def test_pdf_case_skip():
    _card()
    assert "case nahi bana" in say("skip")
    assert _cases == []


def test_no_card_when_pdf_has_no_dates():
    _sessions[PHONE] = ("idle", {})
    assert offer_case_from_pdf(PHONE, "f", {"court": "X"}) is None
    assert offer_case_from_pdf(PHONE, "f", None) is None


def test_pdf_card_replaces_unfinished_flow():
    _sessions[PHONE] = ("awaiting_file_case", {"file_id": "old", "case_ids": ["x"]})
    card = offer_case_from_pdf(PHONE, "file-9", PDF_INFO)
    assert card and "PDF se case ki details" in card
    assert _sessions[PHONE][0] == "awaiting_pdf_case"


def test_no_pdf_card_during_onboarding():
    _sessions[PHONE] = ("onboard_city", {})
    assert offer_case_from_pdf(PHONE, "file-9", PDF_INFO) is None
