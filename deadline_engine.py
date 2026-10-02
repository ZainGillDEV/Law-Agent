"""
Deterministic Limitation Act 1908 deadline engine.

- Article data comes from limitation_articles.json (extracted from the First Schedule PDF).
- The LLM may only SUGGEST which article applies (see article_matcher.py).
  The deadline itself is always computed here, by fixed rules. Never by the LLM.
"""
import calendar
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

DISCLAIMER = "⚠️ Verify independently — not a substitute for professional judgment."
DATA_FILE = Path(__file__).with_name("limitation_articles.json")
SCHEDULE = "Limitation Act 1908, First Schedule"


@dataclass(frozen=True)
class Article:
    article: str          # "152", "11A", "CPC-48"
    division: str         # Suits / Appeals / Applications / Other
    description: str
    period: str           # "Thirty days" (as written in the statute)
    starts_from: str      # time from which the period begins
    years: int = 0
    months: int = 0
    days: int = 0
    needs_review: bool = False
    note: str = ""
    source: str = SCHEDULE

    @property
    def citation(self) -> str:
        if self.source == SCHEDULE:
            return f"{SCHEDULE}, Art. {self.article}"
        return self.source

    @property
    def label(self) -> str:
        """Short name for menus and the cases table."""
        prefix = f"Art. {self.article}" if self.source == SCHEDULE else self.source.split(",")[-1].strip()
        desc = self.description if len(self.description) <= 70 else self.description[:67] + "..."
        return f"{prefix} — {desc}"


def _load() -> tuple[dict[str, Article], bool]:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    articles: dict[str, Article] = {}
    for a in raw["articles"]:
        art = Article(
            article=a["art"], division=a["div"], description=a["desc"],
            period=a["period"], starts_from=a["from"],
            years=a.get("y", 0), months=a.get("m", 0), days=a.get("d", 0),
            needs_review=a.get("review", False), note=a.get("note", ""),
            source=a.get("source", SCHEDULE),
        )
        if sum(1 for v in (art.years, art.months, art.days) if v) != 1:
            raise ValueError(f"Article {art.article}: exactly one of years/months/days must be set")
        if art.article.upper() in articles:
            raise ValueError(f"Duplicate article {art.article}")
        articles[art.article.upper()] = art
    return articles, raw.get("verified_by_lawyer", False)


ARTICLES, VERIFIED_BY_LAWYER = _load()


def get_article(text: str) -> Article | None:
    """'152', 'art 152', 'Article 11A', 'art. 64a', 'cpc-48' -> Article (or None)."""
    t = text.strip().upper()
    t = re.sub(r"^(ARTICLE|ART)\.?\s*", "", t)
    return ARTICLES.get(t)


@dataclass(frozen=True)
class DeadlineResult:
    deadline: date
    article: Article
    start_date: date
    rolled_forward: bool  # Section 4: court closed on last day -> next working day


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])  # 31 Jan + 1 month -> 28/29 Feb
    return date(year, month, day)


def compute_deadline(article_no: str, start_date: date,
                     holidays: frozenset[date] = frozenset()) -> DeadlineResult:
    art = get_article(article_no)
    if art is None:
        raise KeyError(f"Unknown article: {article_no}")

    # Section 12(1): the day from which the period is reckoned is excluded,
    # so "30 days from 1 Jan" = 31 Jan -> plain date addition gives this.
    deadline = _add_months(start_date, art.years * 12 + art.months)
    deadline += timedelta(days=art.days)

    # Section 4: if the court is closed on the last day, file on the next working day.
    rolled = False
    while deadline.weekday() == 6 or deadline in holidays:  # 6 = Sunday
        deadline += timedelta(days=1)
        rolled = True

    return DeadlineResult(deadline, art, start_date, rolled)


def article_card(art: Article) -> str:
    """One article, formatted for a WhatsApp list."""
    text = f"*{art.label}*\n   ⏳ {art.period} — from: {art.starts_from}"
    if art.needs_review:
        text += "\n   🔎 needs review"
    return text


_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})


def parse_date(text: str, today: date | None = None) -> date | None:
    """Pakistani day-first dates: 12/3/2025, 12-03-25, 12.3.2025, 12 March 2025, 12 mar 25, today/aaj."""
    today = today or date.today()
    t = text.strip().lower()

    if t in {"today", "aaj"}:
        return today
    if t in {"yesterday", "kal"}:  # "kal" is ambiguous in Urdu; used as yesterday for past dates
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
    except ValueError:  # 31/02/2025
        return None


def format_deadline_reply(result: DeadlineResult) -> str:
    a = result.article
    msg = (
        f"📅 *Limitation deadline: {result.deadline.strftime('%d %b %Y')}*\n"
        f"Article: {a.label}\n"
        f"Period: {a.period}\n"
        f"Counted from: {a.starts_from} ({result.start_date.strftime('%d %b %Y')})\n"
        f"Reference: {a.citation}\n"
    )
    if result.rolled_forward:
        msg += "ℹ️ Last day was a court holiday, moved to next working day (Sec. 4).\n"
    if a.needs_review:
        msg += f"🔎 Needs review: {a.note}\n"
    if not VERIFIED_BY_LAWYER:
        msg += "🔎 Article data has not yet been verified by a lawyer.\n"
    msg += f"\n{DISCLAIMER}"
    return msg
