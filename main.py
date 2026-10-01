import logging

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402

from db import supabase  # noqa: E402
from webhook import router as webhook_router  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s: %(message)s")

app = FastAPI(title="LawAiAgentMVP")
app.include_router(webhook_router)


@app.get("/health")
def health():
    result = supabase.table("lawyers").select("phone_number").limit(1).execute()
    return {"status": "ok", "db": "connected", "rows_checked": len(result.data)}