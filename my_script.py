"""
Poll Eliis for new received messages, translate Estonian → English via OpenAI,
post each one to Telegram with any attachments (photos/videos as media groups,
docs as documents). Tracks progress in last_message_id.txt — every message id
strictly greater than that gets processed (oldest first), so bursts between
runs are not dropped.
"""
import json
import os

import requests

from translator import chat as translate_chat, strip_html

ELIIS_API = "https://api.eliis.eu/api"
TELEGRAM_API_BASE = "https://api.telegram.org"
CHANNEL_ID = "-1002622203486"
LAST_ID_FILE = "last_message_id.txt"
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096

csrf_token = (os.getenv("ELIIS_CSRF_TOKEN") or "").strip()
bot_token = (os.getenv("BOT_TOKEN") or "").strip()

TELEGRAM_API = f"{TELEGRAM_API_BASE}/bot{bot_token}"

eliis_headers = {
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://eliis.eu",
    "Referer": "https://eliis.eu/",
    "Cookie": f"lang=en; eliis_csrf={csrf_token}",
}


def load_last_id():
    if not os.path.exists(LAST_ID_FILE):
        return 0
    try:
        return int(open(LAST_ID_FILE).read().strip() or 0)
    except ValueError:
        return 0


def save_last_id(msg_id):
    with open(LAST_ID_FILE, "w") as f:
        f.write(str(msg_id))


def fetch_new_messages(last_id):
    """Return all messages with id > last_id, ordered ascending."""
    new_msgs = []
    page = 1
    while True:
        url = f"{ELIIS_API}/common/messages/received?page={page}&perPage=50&term="
        resp = requests.get(url, headers=eliis_headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        page_msgs = data.get("data", [])
        if not page_msgs:
            break
        hit_old = False
        for m in page_msgs:
            if m["id"] > last_id:
                new_msgs.append(m)
            else:
                hit_old = True
                break
        if hit_old:
            break
        if data.get("current_page", page) >= data.get("last_page", page):
            break
        page += 1
    new_msgs.sort(key=lambda m: m["id"])
    return new_msgs


def translate(subject, body_text):
    """Translate the message and, if there's a deadline/task/required reply,
    surface it as a one-line action header at the top of the output."""
    prompt = (
        "You are translating an Estonian kindergarten message to English for a parent's Telegram channel.\n"
        "Format your reply EXACTLY as follows:\n"
        "  Line 1: '⚠️ ACTION: <one short line>' — if the message contains a deadline, a required action, "
        "a question that needs a reply, or anything the parent must do. Otherwise output exactly 'INFO'.\n"
        "  Line 2: (blank)\n"
        "  Line 3+: the translation, formatted nicely for Telegram. Allowed HTML: <b> <i> <u> <s> <code> <a>. "
        "Start with the subject as a bold heading on its own line.\n\n"
        f"Subject: {subject}\n\nBody:\n{body_text}"
    )
    raw = translate_chat(
        messages=[
            {"role": "system", "content": "Output exactly the format requested. No code fences."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=2000,
        temperature=0.4,
    )
    head, _, rest = raw.partition("\n\n")
    head = head.strip()
    rest = rest.strip()
    if head.startswith("⚠️ ACTION:") or head.startswith("ACTION:"):
        action = head if head.startswith("⚠️") else "⚠️ " + head
        return f"<b>{action}</b>\n\n{rest}" if rest else f"<b>{action}</b>"
    if head == "INFO":
        return rest or raw
    # Model didn't follow format — return raw output as a fallback
    return raw


def tg_post(endpoint, data=None, files=None):
    r = requests.post(f"{TELEGRAM_API}/{endpoint}", data=data, files=files, timeout=60)
    if r.status_code != 200:
        print(f"  ⚠️  {endpoint} {r.status_code}: {r.text[:300]}")
    return r


def send_text(text):
    """Send text to Telegram, chunking if longer than the message limit. Falls
    back to plain text if HTML parsing fails on a chunk."""
    for i in range(0, len(text), MESSAGE_LIMIT - 100):
        chunk = text[i : i + MESSAGE_LIMIT - 100]
        r = tg_post("sendMessage", data={"chat_id": CHANNEL_ID, "text": chunk, "parse_mode": "HTML"})
        if r.status_code != 200:
            tg_post("sendMessage", data={"chat_id": CHANNEL_ID, "text": chunk})


def download_attachment(file_info):
    url = f"{ELIIS_API}/common/files/messages/{file_info['filename']}"
    r = requests.get(url, headers=eliis_headers, timeout=60)
    r.raise_for_status()
    return r.content


def send_attachments(files, caption=""):
    """Send a message's files to Telegram. Photos/videos go as media groups
    (or sendPhoto/sendVideo if just one), other files as documents.
    `caption` is applied only to the first item sent (and truncated to 1024).
    Returns True if at least one file was successfully sent."""
    media_files = [f for f in files if (f.get("mime_type") or "").startswith(("image/", "video/"))]
    doc_files = [f for f in files if not (f.get("mime_type") or "").startswith(("image/", "video/"))]

    sent_any = False
    caption_consumed = False

    def maybe_caption():
        nonlocal caption_consumed
        if caption and not caption_consumed:
            caption_consumed = True
            return caption[:CAPTION_LIMIT]
        return ""

    # Photos / videos — batch into media groups of up to 10
    for start in range(0, len(media_files), 10):
        batch = media_files[start : start + 10]
        downloaded = []
        for f in batch:
            try:
                downloaded.append((f, download_attachment(f)))
            except Exception as e:
                print(f"  ⚠️  download failed for {f.get('name')}: {e}")
        if not downloaded:
            continue

        first_caption = maybe_caption()

        if len(downloaded) == 1:
            f, content = downloaded[0]
            is_image = f["mime_type"].startswith("image/")
            endpoint = "sendPhoto" if is_image else "sendVideo"
            field = "photo" if is_image else "video"
            r = tg_post(
                endpoint,
                data={"chat_id": CHANNEL_ID, "caption": first_caption, "parse_mode": "HTML"},
                files={field: (f["name"], content, f["mime_type"])},
            )
            if r.status_code == 200:
                sent_any = True
        else:
            files_form = {}
            media_json = []
            for i, (f, content) in enumerate(downloaded):
                attach = f"file{i}"
                files_form[attach] = (f["name"], content, f["mime_type"])
                entry = {
                    "type": "photo" if f["mime_type"].startswith("image/") else "video",
                    "media": f"attach://{attach}",
                }
                if i == 0 and first_caption:
                    entry["caption"] = first_caption
                    entry["parse_mode"] = "HTML"
                media_json.append(entry)
            r = tg_post(
                "sendMediaGroup",
                data={"chat_id": CHANNEL_ID, "media": json.dumps(media_json)},
                files=files_form,
            )
            if r.status_code == 200:
                sent_any = True

    # Documents
    for f in doc_files:
        try:
            content = download_attachment(f)
        except Exception as e:
            print(f"  ⚠️  download failed for {f.get('name')}: {e}")
            continue
        data = {"chat_id": CHANNEL_ID, "parse_mode": "HTML"}
        cap = maybe_caption()
        if cap:
            data["caption"] = cap
        r = tg_post(
            "sendDocument",
            data=data,
            files={"document": (f["name"], content, f.get("mime_type", "application/octet-stream"))},
        )
        if r.status_code == 200:
            sent_any = True

    return sent_any


def process_message(msg):
    subject = msg.get("subject", "") or ""
    body_text = strip_html(msg.get("body", ""))
    files = msg.get("files") or []
    date_str = (msg.get("created_at") or "")[:10]

    translated = translate(subject, body_text)
    if date_str:
        translated = f"📅 <i>{date_str}</i>\n\n{translated}"

    if files:
        if len(translated) <= CAPTION_LIMIT:
            sent_any = send_attachments(files, caption=translated)
            if not sent_any:
                # All attachment downloads/sends failed — still post the text
                send_text(translated)
        else:
            send_text(translated)
            send_attachments(files, caption="")
    else:
        send_text(translated)


def main():
    if not csrf_token:
        raise SystemExit("ELIIS_CSRF_TOKEN is not set")
    if not bot_token:
        raise SystemExit("BOT_TOKEN is not set")

    last_id = load_last_id()
    print(f"Last processed message id: {last_id}")

    new_messages = fetch_new_messages(last_id)
    if not new_messages:
        print("🔁 No new messages.")
        return

    print(f"🆕 {len(new_messages)} new message(s) to process")
    for msg in new_messages:
        print(f"\n— #{msg['id']}: {(msg.get('subject') or '')[:60]}")
        process_message(msg)
        # Persist after each message so a crash mid-batch doesn't replay sent ones
        save_last_id(msg["id"])

    print("\n✅ Done.")


if __name__ == "__main__":
    main()
