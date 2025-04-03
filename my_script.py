import os
import requests

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

print("Subject:", subject)
print("Body:", body)
