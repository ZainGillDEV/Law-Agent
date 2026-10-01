import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from conversation_graph import MAIN_MENU, ask_link_file, handle_text
from db import ensure_lawyer
from file_pipeline import process_pdf
from whatsapp_client import mark_as_read, send_text

router = APIRouter()
log = logging.getLogger("webhook")

_seen_ids: set[str] = set()


@router.get("/webhook")
def verify(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    if mode == "subscribe" and token == os.environ["WHATSAPP_VERIFY_TOKEN"]:
        return PlainTextResponse(challenge)
    return PlainTextResponse("Forbidden", status_code=403)


def _valid_signature(body: bytes, header: str | None) -> bool:
    secret = os.environ.get("META_APP_SECRET", "")
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@router.post("/webhook")
async def receive(request: Request, background_tasks: BackgroundTasks):
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
                    handle_message(msg, value, background_tasks)
                except Exception:
                    log.exception("Error handling message")

    return {"status": "ok"}


def handle_message(msg: dict, value: dict, background_tasks: BackgroundTasks) -> None:
    msg_id = msg.get("id")
    if msg_id in _seen_ids:
        return
    _seen_ids.add(msg_id)

    phone = msg["from"]
    contacts = value.get("contacts", [])
    name = contacts[0].get("profile", {}).get("name") if contacts else None
    mtype = msg.get("type")

    log.info("Message from %s (%s), type=%s", phone, name, mtype)
    mark_as_read(msg_id)

    is_new = ensure_lawyer(phone, name)
    if is_new:
        send_text(phone, f"Assalam-o-Alaikum {name or ''}! 👋\nLawAiAgent mein khush aamdeed.")
        if mtype == "text":
            send_text(phone, MAIN_MENU)
            return

    if mtype == "document":
        doc = msg["document"]
        if doc.get("mime_type") != "application/pdf":
            send_text(phone, "⚠️ Abhi sirf PDF files support hain.")
            return
        send_text(phone, "📄 File mil gayi. Summary bana raha hoon, thora intezar karein...")
        background_tasks.add_task(_process_document, phone, doc["id"],
                                  doc.get("filename", "document.pdf"))
        return

    if mtype == "image":
        send_text(phone, "📷 Photos abhi support nahi hain. Document ko *PDF* bana ke bhejein.")
        return

    if mtype != "text":
        send_text(phone, "Abhi sirf text messages aur PDF files support hain.")
        return

    for reply in handle_text(phone, msg["text"]["body"]):
        send_text(phone, reply)


def _process_document(phone: str, media_id: str, filename: str) -> None:
    """Background mein chalta hai, webhook ko 200 dene ke baad."""
    try:
        reply, file_id = process_pdf(phone, media_id, filename)
        send_text(phone, reply)
        if file_id:
            prompt = ask_link_file(phone, file_id)
            if prompt:
                send_text(phone, prompt)
    except Exception:
        log.exception("PDF processing failed")
        send_text(phone, "⚠️ File process nahi ho saki. Thori dair baad dobara try karein.")