import os
import requests
from openai import OpenAI

csrf_token = os.getenv("ELIIS_CSRF_TOKEN")

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

# Step 1: Call first API
response = requests.get("https://api.eliis.eu/api/common/messages/recent", headers=headers)

data = response.json()
# Get the first (latest) message
latest = data["messages"][0]

subject = latest["subject"]
body = latest["body"]

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

response = client.chat.completions.create(
  model="gpt-3.5-turbo",  # or "gpt-4"
  messages=[
    {"role": "system", "content": "You are a helpful translator."},
    {"role": "user", "content": f"Translate this to English formatted:\n\n{subject}\n\n{body}"}
  ],
  temperature=0.7,
  max_tokens=500
)


translated_text = response.choices[0].message.content
print("✅ Translated text:\n", translated_text)
