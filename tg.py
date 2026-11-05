"""Telegram Bot API helpers: 429 retry, HTML fallback, album → single → text fallback."""
import json
import os
import time

import requests

CHANNEL_ID = "-1002622203486"
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096

_bot = (os.getenv("BOT_TOKEN") or "").strip()
_API = f"https://api.telegram.org/bot{_bot}"


def require_token():
    if not _bot:
        raise SystemExit("BOT_TOKEN is not set")


def post(endpoint, data=None, files=None):
    """POST to Telegram, retrying on 429 with the server-advised backoff. Returns the response."""
    r = None
    for attempt in range(3):
        r = requests.post(f"{_API}/{endpoint}", data=data, files=files, timeout=120)
        if r.status_code == 429 and attempt < 2:
            try:
                wait = float(r.json()["parameters"]["retry_after"])
            except Exception:
                wait = 3
            print(f"  ⏳ Telegram 429 on {endpoint}; sleeping {wait + 0.5}s")
            time.sleep(wait + 0.5)
            continue
        break
    if r.status_code != 200:
        print(f"  ⚠️  {endpoint} {r.status_code}: {r.text[:200]}")
    return r


def send_text(text):
    """Send text, chunked to the message limit. Falls back to plain text if HTML is rejected."""
    ok = True
    step = MESSAGE_LIMIT - 100
    for i in range(0, len(text), step):
        chunk = text[i : i + step]
        r = post("sendMessage", {"chat_id": CHANNEL_ID, "text": chunk, "parse_mode": "HTML"})
        if r.status_code != 200:
            r = post("sendMessage", {"chat_id": CHANNEL_ID, "text": chunk})
        ok = ok and r.status_code == 200
    return ok


def send_media_urls(items, caption=""):
    """Send photos/videos by public URL. Albums of up to 10; if an album is rejected each item
    is retried alone; items that still fail are returned so the caller can link them in text.
    `caption` goes on the first item only."""
    failed = []
    for start in range(0, len(items), 10):
        batch = items[start : start + 10]
        cap = caption if start == 0 else ""
        if len(batch) == 1:
            if not _send_one(batch[0], cap):
                failed.append(batch[0])
            continue
        media = [{"type": it["type"], "media": it["url"]} for it in batch]
        if cap:
            media[0]["caption"] = cap[:CAPTION_LIMIT]
            media[0]["parse_mode"] = "HTML"
        r = post("sendMediaGroup", {"chat_id": CHANNEL_ID, "media": json.dumps(media)})
        if r.status_code == 200:
            continue
        print(f"  ↩️  album rejected; sending {len(batch)} items one by one")
        for i, it in enumerate(batch):
            if not _send_one(it, cap if i == 0 else ""):
                failed.append(it)
    return failed


def _send_one(item, caption):
    ep, field = ("sendVideo", "video") if item["type"] == "video" else ("sendPhoto", "photo")
    data = {"chat_id": CHANNEL_ID, field: item["url"]}
    if caption:
        data.update(caption=caption[:CAPTION_LIMIT], parse_mode="HTML")
    r = post(ep, data)
    if r.status_code != 200 and caption:
        data.pop("parse_mode", None)
        r = post(ep, data)
    return r.status_code == 200


def send_files(files, caption=""):
    """Send downloaded files (list of (name, bytes, mime)). Images/videos as an album,
    the rest as documents. Returns True if anything was delivered."""
    media = [f for f in files if f[2].startswith(("image/", "video/"))]
    docs = [f for f in files if not f[2].startswith(("image/", "video/"))]
    sent = False
    cap = caption
    for start in range(0, len(media), 10):
        batch = media[start : start + 10]
        if len(batch) == 1:
            name, content, mime = batch[0]
            ep, field = ("sendPhoto", "photo") if mime.startswith("image/") else ("sendVideo", "video")
            r = post(ep, {"chat_id": CHANNEL_ID, "caption": cap[:CAPTION_LIMIT], "parse_mode": "HTML"},
                     files={field: (name, content, mime)})
        else:
            form, media_json = {}, []
            for i, (name, content, mime) in enumerate(batch):
                form[f"f{i}"] = (name, content, mime)
                entry = {"type": "photo" if mime.startswith("image/") else "video", "media": f"attach://f{i}"}
                if i == 0 and cap:
                    entry.update(caption=cap[:CAPTION_LIMIT], parse_mode="HTML")
                media_json.append(entry)
            r = post("sendMediaGroup", {"chat_id": CHANNEL_ID, "media": json.dumps(media_json)}, files=form)
        if r.status_code == 200:
            sent, cap = True, ""
    for name, content, mime in docs:
        data = {"chat_id": CHANNEL_ID, "parse_mode": "HTML"}
        if cap:
            data["caption"] = cap[:CAPTION_LIMIT]
        r = post("sendDocument", data, files={"document": (name, content, mime)})
        if r.status_code == 200:
            sent, cap = True, ""
    return sent
