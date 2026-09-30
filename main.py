import os
from fastapi import FastAPI, Query
from fastapi.responses import PlainTextResponse
from db import supabase

app = FastAPI(title="LawAiAgentMVP")


@app.get("/health")
def health():
    result = supabase.table("lawyers").select("phone_number").limit(1).execute()
    return {"status": "ok", "db": "connected", "rows_checked": len(result.data)}


@app.get("/webhook")
def verify(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    if mode == "subscribe" and token == os.environ["WHATSAPP_VERIFY_TOKEN"]:
        return PlainTextResponse(challenge)
    return PlainTextResponse("Forbidden", status_code=403)