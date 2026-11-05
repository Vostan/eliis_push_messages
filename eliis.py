"""Eliis API client. Auth is the eliis_csrf JWT cookie (ELIIS_CSRF_TOKEN)."""
import os
import time

import requests

API = "https://api.eliis.eu/api"
KINDERGARTEN_ID = 383

CHILDREN = [
    {"id": 280632, "name": "Armen"},
    {"id": 293183, "name": "Hayk"},
]

_token = (os.getenv("ELIIS_CSRF_TOKEN") or "").strip()

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://eliis.eu",
    "Referer": "https://eliis.eu/",
    "Cookie": f"lang=en; eliis_csrf={_token}",
}


def require_token():
    if not _token:
        raise SystemExit("ELIIS_CSRF_TOKEN is not set")


def _get(url, **kw):
    """GET with one retry on 5xx / connection errors (Eliis returns 503 now and then)."""
    timeout = kw.get("timeout", 30)
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code >= 500 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def inbox_page(page):
    return _get(f"{API}/common/messages/received?page={page}&perPage=50&term=").json()


def messages_after(last_id):
    """All inbox messages with id > last_id, oldest first. The inbox is newest-first."""
    out = []
    page = 1
    while True:
        data = inbox_page(page)
        msgs = data.get("data", [])
        if not msgs:
            break
        out.extend(m for m in msgs if m["id"] > last_id)
        if any(m["id"] <= last_id for m in msgs):
            break
        if data.get("current_page", page) >= data.get("last_page", page):
            break
        page += 1
    return sorted(out, key=lambda m: m["id"])


def messages_since(cutoff_iso):
    """All inbox messages created on or after cutoff_iso (YYYY-MM-DD)."""
    out = []
    page = 1
    while True:
        data = inbox_page(page)
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


def download_message_file(filename):
    return _get(f"{API}/common/files/messages/{filename}", timeout=60).content


def guardian_feed(child_id, date_iso):
    """One page of the diary feed: ~5 dated entries ending at date_iso, plus next_date."""
    return _get(
        f"{API}/kindergartens/{KINDERGARTEN_ID}/children/{child_id}/guardian-feed"
        f"?page=1&date={date_iso}"
    ).json()


def diary_text(diary):
    """Plain text of all summaries in a diary entry (HTML stripped)."""
    from translator import strip_html

    parts = []
    for block in diary.get("texts", []):
        for s in block.get("summaries", []):
            t = strip_html(s.get("comment", ""))
            if t:
                parts.append(t)
    return "\n\n".join(parts)


def diary_media(diary):
    """Images/videos of a diary entry as dicts: id, url, type, thumb."""
    out = []
    for block in diary.get("texts", []):
        for im in block.get("images", []):
            url = im.get("url")
            if not url:
                continue
            is_video = (im.get("mime_type") or "").startswith("video/")
            thumbs = im.get("thumbnails") or {}
            thumb = (thumbs.get("small") or thumbs.get("medium") or {}).get("url") or url
            out.append({"id": im["id"], "url": url, "type": "video" if is_video else "photo", "thumb": thumb})
    return out
