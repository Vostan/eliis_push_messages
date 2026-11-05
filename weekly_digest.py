"""Sunday summary of the trailing 7 days (inbox + both diaries) as one Telegram message.
Stateless; safe to run manually any time (python weekly_digest.py)."""
from datetime import date, timedelta

import eliis
import tg
from translator import chat, strip_html


def diaries_since(child_id, cutoff_iso):
    out, current = [], date.today().isoformat()
    while current and current >= cutoff_iso:
        data = eliis.guardian_feed(child_id, current)
        for day in data.get("data", []):
            if day["date"] < cutoff_iso:
                return out
            for diary in day.get("diaries", []):
                text = eliis.diary_text(diary)
                if text:
                    out.append(f"[{day['date']} {diary.get('course', '')}]\n{text}")
        current = data.get("next_date")
    return out


def main():
    eliis.require_token()
    tg.require_token()
    today = date.today()
    cutoff = (today - timedelta(days=7)).isoformat()
    print(f"Digest window {cutoff} → {today}")

    msgs = eliis.messages_since(cutoff)
    sections = [f"DATE RANGE: {cutoff} → {today}"]
    sections.append("MESSAGES:\n" + ("\n\n---\n\n".join(
        f"[{(m.get('created_at') or '')[:10]}] {m.get('subject') or ''}\n{strip_html(m.get('body', ''))}" for m in msgs
    ) or "(none)"))
    names = []
    any_diary = False
    for child in eliis.CHILDREN:
        entries = diaries_since(child["id"], cutoff)
        any_diary = any_diary or bool(entries)
        names.append(child["name"])
        sections.append(f"{child['name'].upper()} DIARY:\n" + ("\n\n---\n\n".join(entries) or "(none)"))
    if not msgs and not any_diary:
        print("Nothing to summarize.")
        return

    body = chat(
        [
            {"role": "system", "content": "You are a concise, warm summarizer for parents."},
            {"role": "user", "content": (
                "Summarize these Estonian kindergarten communications from the past week in English for Telegram. "
                "Allowed HTML: <b> <i> <u> <s> <code> <a> only. No top-level heading.\n"
                "1. <b>📩 From the school</b>: 2–5 bullets; surface deadlines/required actions as '⚠️ ...' with dates.\n"
                f"2. For each child ({', '.join(names)}): a <b>👶 Name</b> section with 1–3 bullets.\n"
                "Use • bullets, omit empty sections, stay under 3500 characters.\n\n"
                + "\n\n========\n\n".join(sections)
            )},
        ],
        max_tokens=1500, temperature=0.5,
    )
    tg.send_text(f"<b>📰 Weekly digest — 📅 {cutoff} → {today}</b>\n\n{body}")
    print("✅ digest posted")


if __name__ == "__main__":
    main()
