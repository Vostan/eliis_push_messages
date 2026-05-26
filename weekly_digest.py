"""
Once-a-week summary of inbox messages and diary entries across both
children, posted as a single Telegram message. Stateless — always uses
the trailing 7 days from "now", so running it manually mid-week is safe
(you'll just get a partial-week digest).
"""
import os
from datetime import date, timedelta

import requests

from translator import chat, strip_html

ELIIS_API = "https://api.eliis.eu/api"
CHANNEL_ID = "-1002622203486"
KINDERGARTEN_ID = 383
TELEGRAM_API_BASE = "https://api.telegram.org"
MESSAGE_LIMIT = 4096

CHILDREN = [
    {"id": 280632, "name": "Child 1"},
    {"id": 293183, "name": "Child 2"},
]

csrf_token = (os.getenv("ELIIS_CSRF_TOKEN") or "").strip()
bot_token = (os.getenv("BOT_TOKEN") or "").strip()

eliis_headers = {
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://eliis.eu",
    "Referer": "https://eliis.eu/",
    "Cookie": f"lang=en; eliis_csrf={csrf_token}",
}


def fetch_messages_since(cutoff_iso):
    """All inbox messages with created_at on or after cutoff_iso (YYYY-MM-DD)."""
    out = []
    page = 1
    while True:
        url = f"{ELIIS_API}/common/messages/received?page={page}&perPage=50&term="
        r = requests.get(url, headers=eliis_headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        msgs = data.get("data", [])
        if not msgs:
            break
        for m in msgs:
            if (m.get("created_at") or "")[:10] < cutoff_iso:
                return out
            out.append(m)
        if data.get("current_page", page) >= data.get("last_page", page):
            break
        page += 1
    return out


def fetch_diaries_since(child_id, cutoff_iso):
    """All diary entries with date on or after cutoff_iso."""
    out = []
    current_date = date.today().isoformat()
    while current_date and current_date >= cutoff_iso:
        url = (
            f"{ELIIS_API}/kindergartens/{KINDERGARTEN_ID}"
            f"/children/{child_id}/guardian-feed?page=1&date={current_date}"
        )
        r = requests.get(url, headers=eliis_headers, timeout=30)
        if r.status_code != 200:
            break
        data = r.json()
        for date_entry in data.get("data", []):
            d = date_entry.get("date", "")
            if d < cutoff_iso:
                return out
            for diary in date_entry.get("diaries", []):
                texts = []
                for tb in diary.get("texts", []):
                    for s in tb.get("summaries", []):
                        c = strip_html(s.get("comment", ""))
                        if c:
                            texts.append(c)
                if texts:
                    out.append({"date": d, "course": diary.get("course", ""), "text": "\n\n".join(texts)})
        next_date = data.get("next_date")
        if not next_date:
            break
        current_date = next_date
    return out


def build_digest(messages, diaries_by_child, date_from, date_to):
    sections = [f"DATE RANGE: {date_from} → {date_to}"]
    if messages:
        msg_lines = []
        for m in messages:
            subj = m.get("subject", "") or "(no subject)"
            body = strip_html(m.get("body", ""))
            msg_lines.append(f"[{(m.get('created_at') or '')[:10]}] {subj}\n{body}")
        sections.append("MESSAGES:\n" + "\n\n---\n\n".join(msg_lines))
    else:
        sections.append("MESSAGES: (none this week)")
    for name, entries in diaries_by_child.items():
        if entries:
            entry_lines = [f"[{e['date']} {e['course']}]\n{e['text']}" for e in entries]
            sections.append(f"{name.upper()} DIARY:\n" + "\n\n---\n\n".join(entry_lines))
        else:
            sections.append(f"{name.upper()} DIARY: (no entries this week)")

    source = "\n\n========\n\n".join(sections)
    child_names = ", ".join(diaries_by_child.keys())

    body = chat(
        messages=[
            {"role": "system", "content": "You are a concise, warm summarizer for parents."},
            {
                "role": "user",
                "content": (
                    "Summarize the following Estonian kindergarten communications from the past week "
                    "in English, for a parent reading on Telegram. Format with Telegram-supported HTML "
                    "only (<b> <i> <u> <s> <code> <a>) — no <p>, <ul>, etc. Do NOT include a top-level "
                    "heading; that will be added by the caller.\n\n"
                    "Structure:\n"
                    f"1. <b>📩 From the school</b>: 2–5 bullets of the key inbox messages. "
                    "Surface deadlines/required actions explicitly (e.g. '⚠️ Submit form by 2 June'). "
                    "Reference the date of each item in parentheses, e.g. '(2026-05-23)'.\n"
                    f"2. For each child ({child_names}): a <b>👶 Child name</b> section with 1–3 "
                    "bullets recapping their week. Reference dates in parentheses where useful.\n"
                    "Use • for bullets. Omit a section if it has no content. "
                    "Keep total length under 3500 characters.\n\n"
                    "Source material:\n\n"
                    + source
                ),
            },
        ],
        max_tokens=2000,
        temperature=0.5,
    )
    heading = f"<b>📰 Weekly digest — 📅 {date_from} → {date_to}</b>"
    return f"{heading}\n\n{body}"


def send_telegram(text):
    api = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    for i in range(0, len(text), MESSAGE_LIMIT - 100):
        chunk = text[i : i + MESSAGE_LIMIT - 100]
        r = requests.post(api, data={"chat_id": CHANNEL_ID, "text": chunk, "parse_mode": "HTML"})
        if r.status_code != 200:
            print(f"  ⚠️  sendMessage {r.status_code}: {r.text[:300]}")
            requests.post(api, data={"chat_id": CHANNEL_ID, "text": chunk})


def main():
    if not csrf_token:
        raise SystemExit("ELIIS_CSRF_TOKEN is not set")
    if not bot_token:
        raise SystemExit("BOT_TOKEN is not set")

    today = date.today()
    cutoff = today - timedelta(days=7)
    cutoff_iso = cutoff.isoformat()
    today_iso = today.isoformat()
    print(f"Weekly digest window: {cutoff_iso} → {today_iso}")

    messages = fetch_messages_since(cutoff_iso)
    print(f"  inbox messages: {len(messages)}")

    diaries_by_child = {}
    for child in CHILDREN:
        entries = fetch_diaries_since(child["id"], cutoff_iso)
        diaries_by_child[child["name"]] = entries
        print(f"  {child['name']} diary entries: {len(entries)}")

    if not messages and not any(diaries_by_child.values()):
        print("Nothing to summarize this week — skipping post.")
        return

    digest = build_digest(messages, diaries_by_child, cutoff_iso, today_iso)
    send_telegram(digest)
    print("✅ Digest posted.")


if __name__ == "__main__":
    main()
