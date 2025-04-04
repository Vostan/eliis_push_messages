import os
import requests
from openai import OpenAI
import json
from io import BytesIO

csrf_token = os.getenv("ELIIS_CSRF_TOKEN")

LAST_ID_FILE = "last_message_id.txt"

if os.path.exists(LAST_ID_FILE):
  with open(LAST_ID_FILE, "r") as f:
    last_processed_id = f.read().strip()
else:
  last_processed_id = None

headers = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:137.0) Gecko/20100101 Firefox/137.0',
  'Accept': 'application/json, text/plain, */*',
  'Accept-Language': 'en-US,en;q=0.5',
  'Accept-Encoding': 'gzip, deflate, br, zstd',
  'X-Requested-With': 'XMLHttpRequest',
  'X-Socket-ID': '4253393906.9874578411',
  'Origin': 'https://eliis.eu',
  'Connection': 'keep-alive',
  'Referer': 'https://eliis.eu/',
  'Cookie': f'lang=en; eliis_csrf={csrf_token}',
  'Sec-Fetch-Dest': 'empty',
  'Sec-Fetch-Mode': 'cors',
  'Sec-Fetch-Site': 'same-site',
  'TE': 'trailers'
}

# Call eliis
response = requests.get("https://api.eliis.eu/api/common/messages/recent", headers=headers)

data = response.json()

latest_message = data["messages"][0]
latest_id = str(latest_message["id"])

if latest_id == last_processed_id:
  print("🔁 Already processed this message. Skipping.")
  exit()

# Process the new message
print("🆕 Processing new message:", latest_id)

latest = data["messages"][0]

subject = latest["subject"]
body = latest["body"]

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

response = client.chat.completions.create(
  model="gpt-3.5-turbo",  # or "gpt-4"
  messages=[
    {"role": "system", "content": "You are a helpful translator."},
    {"role": "user", "content": f"Translate this to English formatted (make it nicely readable for telegram):\n\n{subject}\n\n{body}"}
  ],
  temperature=0.7,
  max_tokens=500
)

translated_text = response.choices[0].message.content

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = "-1002622203486"

if latest.get("files"):
    for idx, file_info in enumerate(latest["files"]):
        # Construct the file URL; adjust if needed
        file_url = f"https://api.eliis.eu/api/common/files/messages/{file_info['filename']}"
        file_response = requests.get(file_url, headers={'Cookie': f'lang=en; eliis_csrf={csrf_token}'})
        file_response.raise_for_status()
        # Ensure BytesIO is imported at the top of the file
        file_obj = BytesIO(file_response.content)
        file_obj.name = file_info["name"]

        # Choose endpoint based on file mime type
        if file_info.get("mime_type", "").startswith("image/"):
            endpoint = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
            file_field = "photo"
        else:
            endpoint = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
            file_field = "document"

        # For the first file, include the translated text as caption
        payload = {
            "chat_id": CHANNEL_ID,
            "caption": translated_text if idx == 0 else "",
            "parse_mode": "HTML"
        }
        files = {file_field: (file_obj.name, file_obj)}
        resp = requests.post(endpoint, data=payload, files=files)
        print(f"✅ Telegram file {idx} status:", resp.status_code)
        print(resp.text)
        file_obj.close()
else:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
      "chat_id": CHANNEL_ID,
      "text": translated_text,
      "parse_mode": "HTML"  # or "Markdown"
    }
    resp = requests.post(url, data=payload)
    print("✅ Telegram status:", resp.status_code)
    print(resp.text)

with open(LAST_ID_FILE, "w") as f:
  f.write(latest_id)
