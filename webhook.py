import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from conversation_graph import MAIN_MENU, handle_text
from db import ensure_lawyer
from whatsapp_client import mark_as_read, send_text

router = APIRouter()
log = logging.getLogger("webhook")

# Meta kabhi kabhi ek hi message do baar bhejta hai, is liye IDs yaad rakhte hain
_seen_ids: set[str] = set()


@router.get("/webhook")
def verify(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook register karte waqt yeh call karta hai."""
    if mode == "subscribe" and token == os.environ["WHATSAPP_VERIFY_TOKEN"]:
        return PlainTextResponse(challenge)
    return PlainTextResponse("Forbidden", status_code=403)


def _valid_signature(body: bytes, header: str | None) -> bool:
    """Check karo ke request waqai Meta se aayi hai."""
    secret = os.environ.get("META_APP_SECRET", "")
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@router.post("/webhook")
async def receive(request: Request):
    body = await request.body()
    if not _valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        log.warning("Invalid signature, request rejected")
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                try:
                    handle_message(msg, value)
                except Exception:
                    log.exception("Error handling message")

    # Hamesha 200 wapas karo, warna Meta baar baar retry karta hai
    return {"status": "ok"}




def handle_message(msg: dict, value: dict) -> None:
    msg_id = msg.get("id")
    if msg_id in _seen_ids:
        return
    _seen_ids.add(msg_id)

    phone = msg["from"]
    contacts = value.get("contacts", [])
    name = contacts[0].get("profile", {}).get("name") if contacts else None

    log.info("Message from %s (%s), type=%s", phone, name, msg.get("type"))
    mark_as_read(msg_id)

    is_new = ensure_lawyer(phone, name)

    if msg.get("type") != "text":
        send_text(phone, "Abhi sirf text messages support hain. PDF upload jald aa raha hai.")
        return

    if is_new:
        send_text(phone, f"Assalam-o-Alaikum {name or ''}! 👋\nLawAiAgent mein khush aamdeed.")
        send_text(phone, MAIN_MENU)
        return

    for reply in handle_text(phone, msg["text"]["body"]):
        send_text(phone, reply)