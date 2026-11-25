"""Telegram delivery for the Alen brief. Chunked sendMessage; long briefs go lead + sendDocument."""
import os

import httpx

API = "https://api.telegram.org"
CHUNK = 3900  # headroom under Telegram's 4096-char message cap


def _chunks(text):
    parts, cur = [], ""
    for block in text.split("\n\n"):
        while len(block) > CHUNK:  # pathological single block
            parts.append(block[:CHUNK])
            block = block[CHUNK:]
        if len(cur) + len(block) + 2 > CHUNK:
            parts.append(cur)
            cur = block
        else:
            cur = cur + "\n\n" + block if cur else block
    if cur:
        parts.append(cur)
    return parts


async def deliver_brief(brief: str) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "8355020994")
    base = API + "/bot" + token
    async with httpx.AsyncClient(timeout=60) as client:
        if len(brief) <= 12000:
            sent = []
            for chunk in _chunks(brief):
                r = await client.post(base + "/sendMessage",
                                      json={"chat_id": chat_id, "text": chunk})
                sent.append(r.status_code)
            return {"mode": "messages", "messages": len(sent), "status": sent}
        lead = brief[:CHUNK]
        r1 = await client.post(base + "/sendMessage", json={"chat_id": chat_id, "text": lead})
        r2 = await client.post(base + "/sendDocument",
                               data={"chat_id": chat_id},
                               files={"document": ("alen_weekly_brief.md", brief.encode("utf-8"))})
        return {"mode": "lead+document", "lead_status": r1.status_code, "doc_status": r2.status_code}
