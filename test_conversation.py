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
fake_db.insert_case = lambda row: _cases.append(row) or row
fake_db.list_active_cases = lambda phone: [c for c in _cases if c["lawyer_phone"] == phone]
fake_db.update_hearing = lambda *a: None
fake_db.link_file_to_case = lambda *a: None
sys.modules["db"] = fake_db

# ---------- Fake LLM ----------
fake_llm = types.ModuleType("llm_client")
fake_llm.chat = lambda system, user, **kw: '{"articles": ["152", "156"]}'
sys.modules["llm_client"] = fake_llm

from conversation_graph import handle_text  # noqa: E402

PHONE = "923000000000"


def say(text):
    return "\n".join(handle_text(PHONE, text))


def setup_function():
    _sessions.clear()
    _cases.clear()
    _lawyers.clear()
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
