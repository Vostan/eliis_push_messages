"""
Poll Eliis and forward anything new to Telegram. Runs on a schedule (see .github/workflows).

Inbox messages: every message with id > state.last_message_id, oldest first, with attachments.

Diary entries: tracked per entry by CONTENT, not by id. Eliis diary ids are not ordered by
date (an entry can be created days ahead as an empty placeholder) and teachers usually
write the text first and upload photos minutes or hours later. So for each entry we keep
the text hash and the set of image ids we have already posted, and post only what is new:
new/changed text, and new photos as an album.

State lives in state.json and is written after every posted item, then committed by CI.
Usage: python poll.py            # normal run
       python poll.py --dry-run  # show what would be posted, send nothing, save nothing
"""
import hashlib
import json
import os
import sys
from datetime import date, timedelta

import eliis
import tg
from translator import describe_album, strip_html, translate_diary, translate_message

STATE_FILE = "state.json"
KEEP_DAYS = 45  # prune diary state older than this
DRY_RUN = "--dry-run" in sys.argv


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_message_id": 0, "diaries": {}}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state):
    if DRY_RUN:
        return
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, STATE_FILE)


# ── Inbox ────────────────────────────────────────────────────────────────────

def process_message(msg):
    subject = msg.get("subject") or ""
    body = strip_html(msg.get("body", ""))
    sender = (msg.get("sender") or {}).get("name") or ""
    files = msg.get("files") or []
    when = (msg.get("created_at") or "")[:10]
    print(f"— #{msg['id']} {when} {subject[:60]!r} files={len(files)}")

    text = translate_message(subject, body)
    header = f"📅 <i>{when}</i>" + (f" · {sender}" if sender else "")
    text = f"{header}\n\n{text}"
    if DRY_RUN:
        print(text[:400])
        return

    downloaded = []
    for f in files:
        try:
            downloaded.append((f.get("name") or f["filename"], eliis.download_message_file(f["filename"]),
                               f.get("mime_type") or "application/octet-stream"))
        except Exception as e:
            print(f"  ⚠️  attachment {f.get('filename')} failed: {e}")

    if downloaded and len(text) <= tg.CAPTION_LIMIT:
        if not tg.send_files(downloaded, caption=text):
            tg.send_text(text)
    else:
        tg.send_text(text)
        if downloaded:
            tg.send_files(downloaded)


def process_inbox(state):
    last_id = state.get("last_message_id", 0)
    msgs = eliis.messages_after(last_id)
    print(f"📩 Inbox: {len(msgs)} new message(s) after id {last_id}")
    for m in msgs:
        process_message(m)
        state["last_message_id"] = m["id"]
        save_state(state)


# ── Diaries ──────────────────────────────────────────────────────────────────

def text_hash(text):
    return hashlib.sha1(text.encode()).hexdigest()[:12] if text else ""


def post_diary_delta(child, diary, diary_date, text, media, prev):
    """Post what is new in this entry compared to `prev` (None if never seen)."""
    seen_images = set(prev.get("images", [])) if prev else set()
    new_media = [m for m in media if m["id"] not in seen_images]
    new_text = text and text_hash(text) != (prev or {}).get("text", "")
    if not new_text and not new_media:
        return None

    header = f"📒 <b>{child['name']}</b> — 📅 {diary_date}"
    if diary.get("course"):
        header += f"\n<i>{diary['course']}</i>"
    if prev and prev.get("text") and new_text:
        header += "\n✏️ <i>updated</i>"

    body = header
    if new_text:
        body += "\n\n" + translate_diary(text)
    print(f"  🆕 diary {diary['id']} {diary_date}: text={'new' if new_text else 'same'} photos=+{len(new_media)}")

    if DRY_RUN:
        print("   ", body[:300].replace("\n", " | "))
        return {"text": text_hash(text), "images": sorted(seen_images | {m['id'] for m in new_media})}

    posted_images = set(seen_images)
    if new_media:
        desc = describe_album([m["thumb"] for m in new_media if m["type"] == "photo"])
        caption = body + (f"\n\n📸 {desc}" if desc else "")
        if len(caption) > tg.CAPTION_LIMIT:
            tg.send_text(body)
            caption = header + (f"\n📸 {desc}" if desc else "")
        failed = tg.send_media_urls(new_media, caption=caption[: tg.CAPTION_LIMIT])
        if failed:
            links = "\n".join(f'<a href="{m["url"]}">{m["type"]} {i + 1}</a>' for i, m in enumerate(failed))
            tg.send_text(f"{header}\n\n⚠️ Telegram rejected {len(failed)} file(s), open directly:\n{links}")
        posted_images |= {m["id"] for m in new_media}  # never retry forever
    else:
        if not tg.send_text(body):
            return None  # leave state untouched so the next run retries

    return {"text": text_hash(text), "images": sorted(posted_images)}


def process_diaries(state):
    diaries_state = state.setdefault("diaries", {})
    today = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()

    for child in eliis.CHILDREN:
        key = str(child["id"])
        print(f"👶 {child['name']} diary feed @ {today}")
        try:
            feed = eliis.guardian_feed(child["id"], today)
        except Exception as e:
            print(f"  ❌ feed failed: {e}")
            continue
        seen = diaries_state.get(key)
        first_run = seen is None
        if first_run:
            seen = diaries_state[key] = {}
            print("  📍 first run for this child: recording current entries, posting nothing")

        for day in feed.get("data", []):
            for diary in day.get("diaries", []):
                did = str(diary["id"])
                text = eliis.diary_text(diary)
                media = eliis.diary_media(diary)
                if first_run:
                    seen[did] = {"date": day["date"], "text": text_hash(text), "images": sorted(m["id"] for m in media)}
                    continue
                result = post_diary_delta(child, diary, day["date"], text, media, seen.get(did))
                if result:
                    seen[did] = {"date": day["date"], **result}
                    save_state(state)

        for did in [d for d, v in seen.items() if v.get("date", "") < cutoff]:
            del seen[did]
        save_state(state)


def main():
    eliis.require_token()
    if not DRY_RUN:
        tg.require_token()
    state = load_state()
    errors = []
    for step in (process_inbox, process_diaries):
        try:
            step(state)
        except Exception as e:  # one feed failing must not stop the other
            print(f"❌ {step.__name__} crashed: {type(e).__name__}: {e}")
            errors.append(step.__name__)
    save_state(state)
    if errors:
        sys.exit(f"failed: {', '.join(errors)}")
    print("✅ done")


if __name__ == "__main__":
    main()
