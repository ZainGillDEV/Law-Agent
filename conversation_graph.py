"""
WhatsApp conversation state machine.
State Supabase ki session_state table mein rehti hai, is liye server restart pe bhi
lawyer wahin se continue karta hai jahan chhoda tha.
"""
from datetime import date

from db import get_session, insert_case, list_active_cases, set_session, update_hearing
from deadline_engine import (
    DISCLAIMER, RULES, RULES_BY_KEY, compute_deadline,
    format_deadline_reply, parse_date, rule_from_menu_choice, rules_menu,
)

# ---------- Keywords (English + Roman Urdu) ----------
CANCEL = {"cancel", "stop", "band", "ruko", "exit", "khatam", "wapas"}
YES = {"1", "yes", "y", "haan", "han", "ha", "ji", "confirm", "ok", "save"}
NO = {"2", "no", "n", "nahi", "nahin", "na"}
SKIP = {"skip", "nahi", "nahin", "no", "-", "pata nahi"}
ADD = {"1", "add", "add case", "new case", "naya case", "case add"}
LIST = {"2", "list", "my cases", "cases", "case list", "list my cases",
        "mera case list dikhao", "mere cases", "mere case"}
UPDATE = {"3", "update", "update hearing", "hearing", "hearing update"}

OTHER_CHOICE = str(len(RULES) + 1)

MAIN_MENU = (
    "*LawAiAgent Menu*\n"
    "1. Add case — naya case add karein\n"
    "2. List cases — apne cases dekhein\n"
    "3. Update hearing — agli peshi ki date badlein\n\n"
    "Kisi bhi waqt *cancel* likh kar wapas aa sakte hain."
)


def _fmt(d_iso: str | None) -> str:
    return date.fromisoformat(d_iso).strftime("%d %b %Y") if d_iso else "—"


# ---------- Entry point ----------
def handle_text(phone: str, text: str) -> list[str]:
    msg = text.strip()
    low = " ".join(msg.lower().split())
    step, draft = get_session(phone)

    if low in CANCEL:
        set_session(phone, "idle")
        return ["❌ Cancelled.", MAIN_MENU] if step != "idle" else [MAIN_MENU]

    handler = STEPS.get(step, _idle)
    return handler(phone, msg, low, draft)


# ---------- Idle: intent routing (no LLM needed) ----------
def _idle(phone, msg, low, draft):
    if low in ADD:
        set_session(phone, "awaiting_case_type", {})
        return [f"📝 *New case*\nCase type select karein (number bhejein):\n\n{rules_menu()}"]
    if low in LIST:
        return [_cases_text(list_active_cases(phone))]
    if low in UPDATE:
        return _start_update(phone)
    return [MAIN_MENU]


# ---------- Add case flow ----------
def _case_type(phone, msg, low, draft):
    rule = rule_from_menu_choice(low)
    if rule:
        set_session(phone, "awaiting_title", {"rule_key": rule.key, "case_type": rule.label})
        return [f"✅ {rule.label}\n\nCase ka title likhein (e.g. *Ali vs Ahmed*)."]
    if low == OTHER_CHOICE:
        set_session(phone, "awaiting_custom_type", {})
        return ["Case type ka naam likhein (e.g. *489-F*, *Family*, *Bail*)."]
    return [f"⚠️ Sirf number bhejein (1–{OTHER_CHOICE}).\n\n{rules_menu()}"]


def _custom_type(phone, msg, low, draft):
    if len(msg) < 2:
        return ["Case type ka naam likhein (e.g. *489-F*)."]
    set_session(phone, "awaiting_title", {"rule_key": None, "case_type": msg[:60]})
    return [f"✅ {msg[:60]}\nℹ️ Is type ke liye limitation date nahi banegi, sirf hearings track hongi.\n\n"
            "Case ka title likhein (e.g. *Ali vs Ahmed*)."]


def _title(phone, msg, low, draft):
    if len(msg) < 2:
        return ["Case ka title likhein (e.g. *Ali vs Ahmed*)."]
    draft["title"] = msg[:100]
    set_session(phone, "awaiting_filing_date", draft)
    rule = RULES_BY_KEY.get(draft.get("rule_key"))
    what = rule.start_event if rule else "filing date"
    return [f"📅 Date bhejein — *{what}*\nFormat: *12/03/2025* ya *12 March 2025*"]


def _filing_date(phone, msg, low, draft):
    d = parse_date(msg)
    if not d:
        return ["⚠️ Date samajh nahi aayi. Aise bhejein: *12/03/2025*"]
    if d > date.today():
        return ["⚠️ Yeh date future mein hai. Guzri hui date bhejein."]
    draft["filing_date"] = d.isoformat()
    set_session(phone, "awaiting_court", draft)
    return ["🏛️ Court ka naam likhein (e.g. *Civil Court Lahore*)."]


def _court(phone, msg, low, draft):
    if len(msg) < 2:
        return ["Court ka naam likhein."]
    draft["court"] = msg[:100]
    set_session(phone, "awaiting_next_hearing", draft)
    return ["🗓️ Agli peshi (next hearing) ki date bhejein, ya *skip* likhein."]


def _next_hearing(phone, msg, low, draft):
    if low in SKIP:
        draft["next_hearing_date"] = None
    else:
        d = parse_date(msg)
        if not d:
            return ["⚠️ Date samajh nahi aayi. *15/10/2026* jaisi date bhejein ya *skip* likhein."]
        draft["next_hearing_date"] = d.isoformat()
    set_session(phone, "confirm_summary", draft)
    return [
        "📋 *Please confirm:*\n"
        f"Type: {draft['case_type']}\n"
        f"Title: {draft['title']}\n"
        f"Date: {_fmt(draft['filing_date'])}\n"
        f"Court: {draft['court']}\n"
        f"Next hearing: {_fmt(draft.get('next_hearing_date'))}\n\n"
        "1. ✅ Save\n2. ❌ Cancel"
    ]


def _confirm(phone, msg, low, draft):
    if low in NO:
        set_session(phone, "idle")
        return ["❌ Case save nahi hua.", MAIN_MENU]
    if low not in YES:
        return ["*1* (save) ya *2* (cancel) bhejein."]

    row = {
        "lawyer_phone": phone,
        "case_type": draft["case_type"],
        "title": draft["title"],
        "filing_date": draft["filing_date"],
        "court": draft["court"],
        "next_hearing_date": draft.get("next_hearing_date"),
    }
    replies = ["✅ *Case saved!*"]

    if draft.get("rule_key"):
        # Deterministic engine — LLM kabhi deadline nahi banata
        result = compute_deadline(draft["rule_key"], date.fromisoformat(draft["filing_date"]))
        row["limitation_deadline"] = result.deadline.isoformat()
        row["limitation_citation"] = result.rule.citation
        replies.append(format_deadline_reply(result))
        if result.deadline < date.today():
            row["status"] = "time-barred"
            replies.append("🚨 *Yeh deadline guzar chuki hai.* Case 'time-barred' mark hua hai. "
                           "Condonation of delay ke options khud check karein.")
    else:
        replies.append("ℹ️ Is case type ke liye limitation date calculate nahi hui. "
                       f"Hearing reminders milenge.\n\n{DISCLAIMER}")

    insert_case(row)
    set_session(phone, "idle")
    return replies


# ---------- List cases ----------
def _cases_text(cases: list[dict]) -> str:
    if not cases:
        return "Aap ka koi case nahi hai. *1* bhej kar naya case add karein."
    lines = ["📂 *Your cases:*"]
    for i, c in enumerate(cases, start=1):
        lines.append(
            f"\n*{i}. {c.get('title') or c['case_type']}*\n"
            f"   {c['case_type']} — {c.get('court') or ''}\n"
            f"   ⏳ Deadline: {_fmt(c.get('limitation_deadline'))}\n"
            f"   🗓️ Next hearing: {_fmt(c.get('next_hearing_date'))}"
            + ("\n   🚨 time-barred" if c.get("status") == "time-barred" else "")
        )
    return "\n".join(lines)


# ---------- Update hearing ----------
def _start_update(phone):
    cases = list_active_cases(phone)
    if not cases:
        return ["Aap ka koi case nahi hai. *1* bhej kar naya case add karein."]
    set_session(phone, "awaiting_update_choice", {"case_ids": [c["case_id"] for c in cases]})
    return [_cases_text(cases) + "\n\nKis case ki hearing update karni hai? *Number* bhejein."]


def _update_choice(phone, msg, low, draft):
    ids = draft.get("case_ids", [])
    if not low.isdigit() or not 1 <= int(low) <= len(ids):
        return [f"⚠️ 1 se {len(ids)} tak number bhejein, ya *cancel* likhein."]
    draft["case_id"] = ids[int(low) - 1]
    set_session(phone, "awaiting_update_date", draft)
    return ["🗓️ Nayi hearing date bhejein (e.g. *15/10/2026*)."]


def _update_date(phone, msg, low, draft):
    d = parse_date(msg)
    if not d:
        return ["⚠️ Date samajh nahi aayi. *15/10/2026* jaisi date bhejein."]
    if d < date.today():
        return ["⚠️ Yeh date guzar chuki hai. Agli (future) hearing ki date bhejein."]
    update_hearing(phone, draft["case_id"], d.isoformat())
    set_session(phone, "idle")
    return [f"✅ Next hearing update ho gayi: *{d.strftime('%d %b %Y')}*"]


# ---------- State table (PRD Section 7) ----------
STEPS = {
    "idle": _idle,
    "awaiting_case_type": _case_type,
    "awaiting_custom_type": _custom_type,
    "awaiting_title": _title,
    "awaiting_filing_date": _filing_date,
    "awaiting_court": _court,
    "awaiting_next_hearing": _next_hearing,
    "confirm_summary": _confirm,
    "awaiting_update_choice": _update_choice,
    "awaiting_update_date": _update_date,
}