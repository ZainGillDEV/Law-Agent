import logging
import os

import httpx

log = logging.getLogger("llm")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def chat(system: str, user: str, max_tokens: int = 2000, temperature: float = 0.2) -> str:
    """Groq (OpenAI-compatible) se ek jawab lo."""
    model = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"  # kam sochna, tez aur sasta jawab

    r = httpx.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
        json=body,
        timeout=60,
    )
    if r.status_code >= 400:
        log.error("LLM failed %s: %s", r.status_code, r.text)
    r.raise_for_status()

    content = (r.json()["choices"][0]["message"].get("content") or "").strip()
    if not content:
        raise RuntimeError("LLM ne khaali jawab diya")
    return content