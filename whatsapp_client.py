import os
import logging
import httpx

log = logging.getLogger("whatsapp")


def _url(path: str) -> str:
    version = os.environ.get("GRAPH_API_VERSION", "v25.0")
    phone_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    return f"https://graph.facebook.com/{version}/{phone_id}/{path}"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}",
        "Content-Type": "application/json",
    }


def send_text(to: str, text: str) -> dict:
    """Lawyer ko normal text message bhejo (24-hour window ke andar)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text[:4096]},
    }
    r = httpx.post(_url("messages"), headers=_headers(), json=payload, timeout=15)
    if r.status_code >= 400:
        log.error("send_text failed %s: %s", r.status_code, r.text)
    return r.json()


def mark_as_read(message_id: str) -> None:
    """Lawyer ko blue ticks dikhao."""
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    r = httpx.post(_url("messages"), headers=_headers(), json=payload, timeout=15)
    if r.status_code >= 400:
        log.warning("mark_as_read failed %s: %s", r.status_code, r.text)


def send_template(to: str, name: str, params: list[str], lang: str = "en") -> dict:
    """Approved template bhejo (24-hour window ke bahar bhi chalta hai)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": lang},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in params],
            }],
        },
    }
    r = httpx.post(_url("messages"), headers=_headers(), json=payload, timeout=15)
    if r.status_code >= 400:
        log.error("send_template %s failed %s: %s", name, r.status_code, r.text)
    return r.json() if r.content else {}