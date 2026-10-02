import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(override=True)

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"],
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Lawyers ----------
def ensure_lawyer(phone: str, name: str | None = None) -> bool:
    """Lawyer pehli baar aaya ho to register karo. Naya ho to True."""
    existing = (
        supabase.table("lawyers").select("phone_number")
        .eq("phone_number", phone).limit(1).execute()
    )
    if existing.data:
        return False
    supabase.table("lawyers").insert({"phone_number": phone, "name": name}).execute()
    supabase.table("session_state").insert({"lawyer_phone": phone}).execute()
    return True


def get_lawyer(phone: str) -> dict | None:
    res = (
        supabase.table("lawyers").select("phone_number, name, city, accepted_at")
        .eq("phone_number", phone).limit(1).execute()
    )
    return res.data[0] if res.data else None


def update_lawyer(phone: str, fields: dict) -> None:
    supabase.table("lawyers").update(fields).eq("phone_number", phone).execute()


def accept_terms(phone: str) -> None:
    update_lawyer(phone, {"accepted_at": _now()})


# ---------- Conversation state ----------
def get_session(phone: str) -> tuple[str, dict]:
    res = (
        supabase.table("session_state").select("current_step, draft_case_json")
        .eq("lawyer_phone", phone).limit(1).execute()
    )
    if res.data:
        row = res.data[0]
        return row["current_step"] or "idle", row["draft_case_json"] or {}
    return "idle", {}


def set_session(phone: str, step: str, draft: dict | None = None) -> None:
    supabase.table("session_state").upsert({
        "lawyer_phone": phone,
        "current_step": step,
        "draft_case_json": draft or {},
        "updated_at": _now(),
    }).execute()


# ---------- Cases (hamesha lawyer_phone se filter — data isolation) ----------
def insert_case(row: dict) -> dict:
    return supabase.table("cases").insert(row).execute().data[0]


def list_active_cases(phone: str) -> list[dict]:
    return (
        supabase.table("cases")
        .select("case_id, title, case_type, court, filing_date, "
                "limitation_deadline, next_hearing_date, status")
        .eq("lawyer_phone", phone)
        .neq("status", "closed")
        .order("created_at")
        .execute()
        .data
    )


def update_hearing(phone: str, case_id: str, new_date_iso: str) -> None:
    (
        supabase.table("cases")
        .update({"next_hearing_date": new_date_iso})
        .eq("case_id", case_id)
        .eq("lawyer_phone", phone)  # doosre lawyer ka case kabhi update na ho
        .execute()
    )


# ---------- Case files ----------
def insert_case_file(row: dict) -> dict:
    return supabase.table("case_files").insert(row).execute().data[0]


def link_file_to_case(phone: str, file_id: str, case_id: str) -> None:
    (
        supabase.table("case_files")
        .update({"case_id": case_id})
        .eq("file_id", file_id)
        .eq("lawyer_phone", phone)
        .execute()
    )
