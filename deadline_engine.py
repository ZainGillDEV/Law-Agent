"""
Deterministic Limitation Act 1908 deadline engine.
LLM is NEVER used here. Every rule must be verified by a lawyer before production.
"""
import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

DISCLAIMER = "⚠️ Verify independently — not a substitute for professional judgment."


@dataclass(frozen=True)
class Rule:
    key: str
    label: str
    start_event: str
    citation: str
    years: int = 0
    months: int = 0
    days: int = 0
    verified: bool = False


RULES: list[Rule] = [
    Rule("appeal_district", "Appeal to District Court",
         "date of decree/order",
         "Limitation Act 1908, First Schedule, Art. 152", days=30),
    Rule("appeal_high_court", "Appeal to High Court",
         "date of decree/order",
         "Limitation Act 1908, First Schedule, Art. 156", days=90),
    Rule("money_recovery", "Suit for recovery of money (written contract)",
         "date the debt became due",
         "Limitation Act 1908, First Schedule, Art. 115/116 — VERIFY", years=3),
    Rule("possession", "Suit for possession of immovable property",
         "date of dispossession",
         "Limitation Act 1908, First Schedule, Art. 142", years=12),
    Rule("execution", "Application for execution of a decree",
         "date decree became enforceable",
         "Limitation Act 1908, First Schedule, Art. 181/182 — VERIFY", years=6),
]

RULES_BY_KEY = {r.key: r for r in RULES}


@dataclass(frozen=True)
class DeadlineResult:
    deadline: date
    rule: Rule
    start_date: date
    rolled_forward: bool


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def compute_deadline(rule_key: str, start_date: date,
                     holidays: frozenset[date] = frozenset()) -> DeadlineResult:
    rule = RULES_BY_KEY[rule_key]
    deadline = _add_months(start_date, rule.years * 12 + rule.months)
    deadline += timedelta(days=rule.days)

    rolled = False
    while deadline.weekday() == 6 or deadline in holidays:  # 6 = Sunday
        deadline += timedelta(days=1)
        rolled = True

    return DeadlineResult(deadline, rule, start_date, rolled)


def rules_menu() -> str:
    lines = [f"{i}. {r.label}" for i, r in enumerate(RULES, start=1)]
    lines.append(f"{len(RULES) + 1}. Other / 489-F / Family (no fixed limitation, only hearings)")
    return "\n".join(lines)


def rule_from_menu_choice(choice: str) -> Rule | None:
    choice = choice.strip()
    if choice.isdigit():
        n = int(choice)
        if 1 <= n <= len(RULES):
            return RULES[n - 1]
    return None


_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})


def parse_date(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    t = text.strip().lower()

    if t in {"today", "aaj"}:
        return today
    if t in {"yesterday", "kal"}:
        return today - timedelta(days=1)

    def _year(y: str) -> int:
        n = int(y)
        return n + 2000 if n < 100 else n

    m = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", t)
    if m:
        d, mo, y = int(m[1]), int(m[2]), _year(m[3])
    else:
        m = re.fullmatch(r"(\d{1,2})\s+([a-z]+)\.?,?\s+(\d{2,4})", t)
        if not m or m[2] not in _MONTHS:
            return None
        d, mo, y = int(m[1]), _MONTHS[m[2]], _year(m[3])

    try:
        return date(y, mo, d)
    except ValueError:
        return None


def format_deadline_reply(result: DeadlineResult) -> str:
    r = result.rule
    msg = (
        f"📅 *Limitation deadline: {result.deadline.strftime('%d %b %Y')}*\n"
        f"Case type: {r.label}\n"
        f"Counted from: {r.start_event} ({result.start_date.strftime('%d %b %Y')})\n"
        f"Reference: {r.citation}\n"
    )
    if result.rolled_forward:
        msg += "ℹ️ Last day was a court holiday, moved to next working day (Sec. 4).\n"
    if not r.verified:
        msg += "🔎 This rule has not yet been verified by a lawyer.\n"
    msg += f"\n{DISCLAIMER}"
    return msg