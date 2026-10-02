"""
WhatsApp conversation state machine.
State Supabase ki session_state table mein rehti hai, is liye server restart pe bhi
lawyer wahin se continue karta hai jahan chhoda tha.
"""
from datetime import date

from article_matcher import suggest_articles
from db import (accept_terms, get_lawyer, get_session, insert_case, link_file_to_case,
                list_active_cases, set_session, update_hearing, update_lawyer)
from deadline_engine import (
    DISCLAIMER, article_card, compute_deadline, format_deadline_reply, get_article, parse_date,
)

# ---------- Keywords (English + Roman Urdu) ----------
CANCEL = {"cancel", "stop", "band", "ruko", "exit", "khatam", "wapas"}
MENU_WORDS = {"menu", "help", "hi", "hello", "salam", "aoa", "start", "assalam o alaikum"}
YES = {"1", "yes", "y", "haan", "han", "ha", "ji", "confirm", "ok", "save"}
NO = {"2", "no", "n", "nahi", "nahin", "na"}
SKIP = {"skip", "nahi", "nahin", "no", "-", "pata nahi"}
OTHER = {"other", "none", "0", "489-f", "489f", "bail", "family", "koi nahi"}
ADD = {"1", "add", "add case", "new case", "naya case", "case add"}
LIST = {"2", "list", "my cases", "cases", "case list", "list my cases",
        "mera case list dikhao", "mere cases", "mere case"}
UPDATE = {"3", "update", "update hearing", "hearing", "hearing update"}

MAIN_MENU = (
    "*LawAiAgent Menu*\n"
    "1. Add case — naya case add karein\n"
    "2. List cases — apne cases dekhein\n"
    "3. Update hearing — agli peshi ki date badlein\n\n"
    "📄 Kisi bhi waqt PDF bhej kar summary le sakte hain.\n"
    "Kisi bhi waqt *cancel* likh kar wapas aa sakte hain."
)

CASE_DESC_PROMPT = (
    "📝 *New case*\n"
    "Case ki mukhtasar tafseel likhein: kis cheez ka case hai aur kis forum mein.\n\n"
    "Misal:\n"
    "• *Civil judge ke decree ke khilaf District Judge ko appeal*\n"
    "• *Qarz wapas lene ka suit, paise 2024 mein diye the*\n"
    "• *Ex parte decree set aside karwani hai*\n\n"
    "Agar article pata hai to seedha likhein, e.g. *art 152*.\n"
    "Agar limitation lagu nahi (489-F, bail, family), *other* likhein."
)


PRIVACY_URL = "za-gdev.vercel.app/privacy"

WELCOME = (
    "Assalam-o-Alaikum! LawAiAgent mein khush aamdeed 👋\n"
    "Main aap ke cases ki limitation deadlines aur hearings yaad rakhta hoon.\n\n"
    "Aap ka poora naam? (e.g. *Adv. Zain Ali*)"
)

CONSENT = (
    "*Zaroori:* main jo deadlines batata hoon woh sirf madad ke liye hain, "
    "qanooni mashwara nahi. Har date khud verify karein.\n"
    f"Privacy policy: {PRIVACY_URL}\n\n"
    "1. ✅ Mujhe manzoor hai"
)

ONBOARDING_STEPS = {"onboard_name", "onboard_city", "onboard_consent"}


def _fmt(d_iso: str | None) -> str:
    return date.fromisoformat(d_iso).strftime("%d %b %Y") if d_iso else "—"


# ---------- Onboarding (naya lawyer) ----------
def needs_onboarding(phone: str) -> bool:
    """True jab tak lawyer ne disclaimer manzoor na kiya ho."""
    lawyer = get_lawyer(phone)
    return not (lawyer and lawyer.get("accepted_at"))


def onboarding_prompt(phone: str) -> list[str]:
    """Onboarding shuru karo, ya jis step pe lawyer hai wahi sawal dobara poochho."""
    step, _ = get_session(phone)
    if step == "onboard_city":
        return ["Kis shehar mein practice karte hain? (e.g. *Lahore*)"]
    if step == "onboard_consent":
        return [CONSENT]
    set_session(phone, "onboard_name")
    return [WELCOME]


def _onboard_name(phone, msg, low, draft):
    if len(msg) < 3 or low in MENU_WORDS or low.isdigit():
        return ["Apna poora naam likhein (e.g. *Adv. Zain Ali*)."]
    name = msg[:80]
    update_lawyer(phone, {"name": name})
    set_session(phone, "onboard_city", {"name": name})
    return [f"Shukriya {name}! Kis shehar mein practice karte hain? (e.g. *Lahore*)"]


def _onboard_city(phone, msg, low, draft):
    if len(msg) < 3 or low in MENU_WORDS or low.isdigit():
        return ["Shehar ka naam likhein (e.g. *Lahore*)."]
    update_lawyer(phone, {"city": msg[:50].title()})
    set_session(phone, "onboard_consent", draft)
    return [CONSENT]


def _onboard_consent(phone, msg, low, draft):
    if low not in YES:
        return ["Bot istemal karne ke liye *1* bhej kar manzoori dein.\n\n" + CONSENT]
    accept_terms(phone)
    set_session(phone, "idle")
    name = draft.get("name") or (get_lawyer(phone) or {}).get("name") or ""
    return [f"Shukriya {name}! ✅ Aap ka account tayyar hai.", MAIN_MENU]


# ---------- Entry point ----------
def handle_text(phone: str, text: str) -> list[str]:
    msg = text.strip()
    low = " ".join(msg.lower().split())
    step, draft = get_session(phone)

    # Onboarding ke dauran cancel/menu kaam nahi karte
    if step in ONBOARDING_STEPS:
        return STEPS[step](phone, msg, low, draft)
    if needs_onboarding(phone):
        return onboarding_prompt(phone)

    if low in CANCEL:
        set_session(phone, "idle")
        return ["❌ Cancelled.", MAIN_MENU] if step != "idle" else [MAIN_MENU]

    # "menu" / "hi" kisi bhi step se lawyer ko wapas main menu pe le aaye
    if low in MENU_WORDS:
        if step != "idle":
            set_session(phone, "idle")
        return [MAIN_MENU]

    handler = STEPS.get(step, _idle)
    return handler(phone, msg, low, draft)


# ---------- Idle: intent routing (no LLM needed) ----------
def _idle(phone, msg, low, draft):
    if low in ADD:
        set_session(phone, "awaiting_case_desc", {})
        return [CASE_DESC_PROMPT]
    if low in LIST:
        return [_cases_text(list_active_cases(phone))]
    if low in UPDATE:
        return _start_update(phone)
    return [MAIN_MENU]


# ---------- Add case: find the article ----------
def _select_article(phone, art) -> list[str]:
    draft = {"article": art.article, "case_type": art.label}
    set_session(phone, "awaiting_title", draft)
    reply = f"✅ *{art.label}*\n⏳ {art.period}, from: {art.starts_from}"
    if art.needs_review:
        reply += f"\n🔎 Needs review: {art.note}"
    reply += "\n\nCase ka title likhein (e.g. *Ali vs Ahmed*)."
    return [reply]


def _start_other(phone) -> list[str]:
    set_session(phone, "awaiting_custom_type", {})
    return ["Case type ka naam likhein (e.g. *489-F*, *Bail*, *Family*)."]


def _case_desc(phone, msg, low, draft):
    if low in OTHER:
        return _start_other(phone)

    # Lawyer ne seedha article number likha: "art 152", "152", "11A".
    # Akela "1"-"9" article nahi maana jata (purane menu ki aadat se galti ho sakti hai).
    art = get_article(msg) if (low.startswith("art") or len(low) >= 2) else None
    if art:
        return _select_article(phone, art)

    if len(msg) < 5:
        return ["Thori aur tafseel likhein, ya article number (e.g. *art 152*), ya *other*."]

    suggestions = suggest_articles(msg)
    if not suggestions:
        return ["🔎 Koi article match nahi hua. Tafseel dobara likhein, "
                "article number likhein (e.g. *art 152*), ya *other* likhein."]

    set_session(phone, "awaiting_article_choice",
                {"suggested": [a.article for a in suggestions], "desc": msg[:300]})
    lines = ["🔎 *Mumkina articles:*"]
    for i, a in enumerate(suggestions, start=1):
        lines.append(f"\n{i}. {article_card(a)}")
    lines.append("\n0. Inmein se koi nahi (other)")
    lines.append("\n⚠️ Yeh AI ki suggestion hai. Sahi article aap khud confirm karein. "
                 "Number bhejein, ya koi aur article number likhein (e.g. *art 120*).")
    return ["\n".join(lines)]


def _article_choice(phone, msg, low, draft):
    if low in OTHER:
        return _start_other(phone)
    suggested = draft.get("suggested", [])
    if low.isdigit() and 1 <= int(low) <= len(suggested):
        return _select_article(phone, get_article(suggested[int(low) - 1]))
    # Lawyer apna article khud likh sakta hai
    art = get_article(msg)
    if art and not low.isdigit():
        return _select_article(phone, art)
    return [f"⚠️ 1 se {len(suggested)} tak number bhejein, *0* (other), "
            "ya article number likhein (e.g. *art 120*)."]


def _custom_type(phone, msg, low, draft):
    if len(msg) < 2:
        return ["Case type ka naam likhein (e.g. *489-F*)."]
    set_session(phone, "awaiting_title", {"article": None, "case_type": msg[:60]})
    return [f"✅ {msg[:60]}\nℹ️ Is type ke liye limitation date nahi banegi, sirf hearings track hongi.\n\n"
            "Case ka title likhein (e.g. *Ali vs Ahmed*)."]


# ---------- Add case: details ----------
def _title(phone, msg, low, draft):
    if len(msg) < 2:
        return ["Case ka title likhein (e.g. *Ali vs Ahmed*)."]
    draft["title"] = msg[:100]
    set_session(phone, "awaiting_filing_date", draft)
    art = get_article(draft["article"]) if draft.get("article") else None
    what = art.starts_from if art else "filing date"
    return [f"📅 Yeh date bhejein: *{what}*\nFormat: *12/03/2025* ya *12 March 2025*"]


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

    if draft.get("article"):
        # Deterministic engine — LLM kabhi deadline nahi banata
        result = compute_deadline(draft["article"], date.fromisoformat(draft["filing_date"]))
        row["limitation_deadline"] = result.deadline.isoformat()
        row["limitation_citation"] = result.article.citation
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


# ---------- File ko case se jodna (Phase 4) ----------
def ask_link_file(phone: str, file_id: str) -> str | None:
    """Summary ke baad poochho ke file kis case ki hai. Lawyer kisi aur flow mein ho to mat poochho."""
    step, _ = get_session(phone)
    if step != "idle":
        return None
    cases = list_active_cases(phone)
    if not cases:
        return None
    set_session(phone, "awaiting_file_case",
                {"file_id": file_id, "case_ids": [c["case_id"] for c in cases]})
    return _cases_text(cases) + "\n\n📎 Yeh file kis case ki hai? *Number* bhejein, ya *skip* likhein."


def _file_case(phone, msg, low, draft):
    if low in SKIP:
        set_session(phone, "idle")
        return ["👍 File bina case ke save ho gayi."]
    ids = draft.get("case_ids", [])
    if not low.isdigit() or not 1 <= int(low) <= len(ids):
        return [f"⚠️ 1 se {len(ids)} tak number bhejein, ya *skip* likhein."]
    link_file_to_case(phone, draft["file_id"], ids[int(low) - 1])
    set_session(phone, "idle")
    return ["✅ File case se jod di gayi."]


# ---------- State table (PRD Section 7) ----------
STEPS = {
    "onboard_name": _onboard_name,
    "onboard_city": _onboard_city,
    "onboard_consent": _onboard_consent,
    "idle": _idle,
    "awaiting_case_desc": _case_desc,
    "awaiting_article_choice": _article_choice,
    "awaiting_custom_type": _custom_type,
    "awaiting_title": _title,
    "awaiting_filing_date": _filing_date,
    "awaiting_court": _court,
    "awaiting_next_hearing": _next_hearing,
    "confirm_summary": _confirm,
    "awaiting_update_choice": _update_choice,
    "awaiting_update_date": _update_date,
    "awaiting_file_case": _file_case,
}
