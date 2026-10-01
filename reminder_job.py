"""
Daily reminder job. Roz ek baar chalta hai (Phase 5 mein cron pe lagega).

Usage:
  uv run python reminder_job.py                      # aaj ke reminders bhejo
  uv run python reminder_job.py --dry-run            # sirf dikhao, bhejo nahi
  uv run python reminder_job.py --date 2026-10-07    # kisi aur din ka "aaj" maan ke test karo
  uv run python reminder_job.py --use-text           # template approve hone tak normal text (24h window)
"""
import argparse
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from postgrest.exceptions import APIError

from db import supabase
from whatsapp_client import send_template, send_text

log = logging.getLogger("reminders")
PKT = ZoneInfo("Asia/Karachi")

DEADLINE_OFFSETS = {"7_day": 7, "1_day": 1}


def _fmt(d: date) -> str:
    return d.strftime("%d %b %Y")


def _claim(case_id: str, reminder_type: str, ref_date: date) -> bool:
    """reminders_sent mein row daalo. Pehle se ho to False (duplicate reminder nahi jayega)."""
    try:
        supabase.table("reminders_sent").insert({
            "case_id": case_id,
            "reminder_type": reminder_type,
            "ref_date": ref_date.isoformat(),
        }).execute()
        return True
    except APIError as e:
        if getattr(e, "code", None) == "23505":  # unique violation = already sent
            return False
        raise


def _unclaim(case_id: str, reminder_type: str, ref_date: date) -> None:
    """Send fail hua to claim wapas lo, taake agli baar retry ho sake."""
    (supabase.table("reminders_sent").delete()
     .eq("case_id", case_id).eq("reminder_type", reminder_type)
     .eq("ref_date", ref_date.isoformat()).execute())


def _send(phone: str, template: str, params: list[str], fallback_text: str, use_text: bool) -> bool:
    res = send_text(phone, fallback_text) if use_text else send_template(phone, template, params)
    return bool(res.get("messages"))


def run(today: date, dry_run: bool = False, use_text: bool = False) -> dict:
    stats = {"sent": 0, "skipped": 0, "failed": 0}

    # ---------- Limitation deadlines: 7 din aur 1 din pehle ----------
    for rtype, days in DEADLINE_OFFSETS.items():
        target = today + timedelta(days=days)
        cases = (supabase.table("cases")
                 .select("case_id, lawyer_phone, title, case_type, limitation_deadline")
                 .eq("status", "active")
                 .eq("limitation_deadline", target.isoformat())
                 .execute().data)

        for c in cases:
            title = c.get("title") or c["case_type"]
            params = [title, c["case_type"], _fmt(target), str(days)]
            text = (f"⏰ *Reminder:* Limitation deadline for *{title}* ({c['case_type']}) "
                    f"is on *{_fmt(target)}* — {days} day(s) left.\n"
                    "⚠️ Verify independently.")

            if dry_run:
                log.info("[DRY] %s -> %s %s", c["lawyer_phone"], rtype, title)
                continue
            if not _claim(c["case_id"], rtype, target):
                stats["skipped"] += 1
                continue
            if _send(c["lawyer_phone"], "case_deadline_reminder", params, text, use_text):
                stats["sent"] += 1
            else:
                _unclaim(c["case_id"], rtype, target)
                stats["failed"] += 1

    # ---------- Hearings: 1 din pehle ----------
    tomorrow = today + timedelta(days=1)
    hearings = (supabase.table("cases")
                .select("case_id, lawyer_phone, title, case_type, court, next_hearing_date")
                .neq("status", "closed")
                .eq("next_hearing_date", tomorrow.isoformat())
                .execute().data)

    for c in hearings:
        title = c.get("title") or c["case_type"]
        court = c.get("court") or "court"
        params = [title, court, _fmt(tomorrow)]
        text = f"🗓️ *Reminder:* Next hearing for *{title}* at {court} is *tomorrow ({_fmt(tomorrow)})*."

        if dry_run:
            log.info("[DRY] %s -> hearing %s", c["lawyer_phone"], title)
            continue
        if not _claim(c["case_id"], "hearing_1_day", tomorrow):
            stats["skipped"] += 1
            continue
        if _send(c["lawyer_phone"], "case_hearing_reminder", params, text, use_text):
            stats["sent"] += 1
        else:
            _unclaim(c["case_id"], "hearing_1_day", tomorrow)
            stats["failed"] += 1

    return stats


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="YYYY-MM-DD, testing ke liye 'aaj' badlo")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--use-text", action="store_true")
    a = p.parse_args()

    today = date.fromisoformat(a.date) if a.date else datetime.now(PKT).date()
    log.info("Running reminders for %s", today)
    stats = run(today, dry_run=a.dry_run, use_text=a.use_text)
    log.info("Done: %s", stats)


if __name__ == "__main__":
    main()