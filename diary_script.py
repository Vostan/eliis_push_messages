import os
import json
import requests
from openai import OpenAI
from io import BytesIO
from datetime import date

# ── Config ──────────────────────────────────────────────────────────────────
csrf_token = os.getenv("ELIIS_CSRF_TOKEN")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = "-1002622203486"
KINDERGARTEN_ID = 383

# Update names to match your children
CHILDREN = [
    {"id": 280632, "name": "Child 1"},
    {"id": 293183, "name": "Child 2"},
]

LAST_DIARY_IDS_FILE = "last_diary_ids.json"

# ── Load last-processed diary IDs per child ─────────────────────────────────
if os.path.exists(LAST_DIARY_IDS_FILE):
    with open(LAST_DIARY_IDS_FILE, "r") as f:
        last_diary_ids = json.load(f)
else:
    last_diary_ids = {}

# ── Headers for Eliis API ───────────────────────────────────────────────────
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://eliis.eu",
    "Referer": "https://eliis.eu/",
    "Cookie": f"lang=en; eliis_csrf={csrf_token}",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
today = date.today().isoformat()


def strip_html(html_text):
    """Rough HTML tag stripper for translation input."""
    import re
    text = re.sub(r"<br\s*/?>", "\n", html_text)
    text = re.sub(r"</?p>", "\n", text)
    text = re.sub(r"<li>", "• ", text)
    text = re.sub(r"</li>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def translate(text, child_name, diary_date):
    """Translate Estonian diary text to English via OpenAI."""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful translator."},
            {
                "role": "user",
                "content": (
                    f"Translate this kindergarten diary entry to English. "
                    f"Format it nicely for Telegram. "
                    f"Start with: 📒 <b>{child_name}</b> — {diary_date}\n\n"
                    f"Here is the text:\n\n{text}"
                ),
            },
        ],
        temperature=0.7,
        max_tokens=800,
    )
    return response.choices[0].message.content


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"}
    resp = requests.post(url, data=payload)
    print("  ✅ sendMessage:", resp.status_code)
    if resp.status_code != 200:
        print("  ⚠️", resp.text)
    return resp


def send_telegram_photo(photo_url, caption=""):
    """Send a photo by URL (CDN images don't need auth)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHANNEL_ID,
        "photo": photo_url,
        "caption": caption[:1024] if caption else "",
        "parse_mode": "HTML",
    }
    resp = requests.post(url, data=payload)
    print(f"  ✅ sendPhoto: {resp.status_code}")
    if resp.status_code != 200:
        print("  ⚠️", resp.text)
    return resp


def send_telegram_video(video_url, caption=""):
    """Send a video by URL."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
    payload = {
        "chat_id": CHANNEL_ID,
        "video": video_url,
        "caption": caption[:1024] if caption else "",
        "parse_mode": "HTML",
    }
    resp = requests.post(url, data=payload)
    print(f"  ✅ sendVideo: {resp.status_code}")
    if resp.status_code != 200:
        print("  ⚠️", resp.text)
    return resp


def send_telegram_media_group(media_items, caption=""):
    """Send multiple photos/videos as a media group (album)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup"
    media = []
    for idx, item in enumerate(media_items):
        entry = {
            "type": item["type"],  # "photo" or "video"
            "media": item["url"],
        }
        if idx == 0 and caption:
            entry["caption"] = caption[:1024]
            entry["parse_mode"] = "HTML"
        media.append(entry)
    # Telegram limits media group to 10 items
    for i in range(0, len(media), 10):
        batch = media[i : i + 10]
        cap = caption if i == 0 else ""
        if i > 0:
            for m in batch:
                m.pop("caption", None)
                m.pop("parse_mode", None)
        payload = {"chat_id": CHANNEL_ID, "media": json.dumps(batch)}
        resp = requests.post(url, data=payload)
        print(f"  ✅ sendMediaGroup batch {i // 10 + 1}: {resp.status_code}")
        if resp.status_code != 200:
            print("  ⚠️", resp.text)


# ── Main loop: process each child ──────────────────────────────────────────
for child in CHILDREN:
    child_id = child["id"]
    child_name = child["name"]
    child_key = str(child_id)

    print(f"\n👶 Fetching diary for {child_name} (ID {child_id}), date={today}")

    feed_url = (
        f"https://api.eliis.eu/api/kindergartens/{KINDERGARTEN_ID}"
        f"/children/{child_id}/guardian-feed?page=1&date={today}"
    )
    resp = requests.get(feed_url, headers=headers)
    if resp.status_code != 200:
        print(f"  ❌ API error {resp.status_code}: {resp.text[:200]}")
        continue

    feed_data = resp.json()
    entries = feed_data.get("data", [])

    if not entries:
        print("  ℹ️  No diary entries found.")
        continue

    last_known_id = last_diary_ids.get(child_key)
    new_entries = []

    # Collect all diary IDs across all dates to find new ones
    for date_entry in entries:
        diary_date = date_entry["date"]
        for diary in date_entry.get("diaries", []):
            diary_id = diary["id"]
            # If we have a last known ID, skip entries we've already seen
            if last_known_id and diary_id <= int(last_known_id):
                continue
            new_entries.append({"diary": diary, "date": diary_date})

    if not new_entries:
        print("  🔁 No new diary entries. Skipping.")
        continue

    # Process oldest first
    new_entries.sort(key=lambda e: e["diary"]["id"])

    for entry_info in new_entries:
        diary = entry_info["diary"]
        diary_date = entry_info["date"]
        diary_id = diary["id"]
        course = diary.get("course", "")

        print(f"  🆕 Processing diary {diary_id} ({diary_date}, {course})")

        # Collect all text summaries
        all_text = ""
        for text_block in diary.get("texts", []):
            for summary in text_block.get("summaries", []):
                comment_html = summary.get("comment", "")
                if comment_html:
                    all_text += strip_html(comment_html) + "\n\n"

        # Collect all images and videos
        media_items = []
        for text_block in diary.get("texts", []):
            for img in text_block.get("images", []):
                mime = img.get("mime_type", "")
                url = img.get("url", "")
                if not url:
                    continue
                if mime.startswith("video/"):
                    media_items.append({"type": "video", "url": url})
                else:
                    media_items.append({"type": "photo", "url": url})

        # Translate text if present
        translated = ""
        if all_text.strip():
            translated = translate(all_text.strip(), child_name, diary_date)
        else:
            translated = f"📒 <b>{child_name}</b> — {diary_date}\n({course})"

        # Send to Telegram
        if media_items:
            send_telegram_media_group(media_items, caption=translated)
        else:
            send_telegram_message(translated)

        # Update last processed ID
        last_diary_ids[child_key] = str(diary_id)

    # Save after processing all entries for this child
    with open(LAST_DIARY_IDS_FILE, "w") as f:
        json.dump(last_diary_ids, f)

print("\n✅ Done.")
