import requests

url = "https://www.basketball-reference.com/players/j/jamesle01.html"

with open("paste.txt", "r", encoding="utf-8") as f:
    html = f.read()

payload = {
    "url": url,
    "htmltext": html
}

response = requests.post("http://127.0.0.1:8003/parse", json=payload, timeout=120)
data = response.json()

print("STATUS:", response.status_code)
print("TITLE:", data.get("title"))
print("DOMAIN:", data.get("domain"))
print("PARSEDTEXT LENGTH:", len(data.get("parsedtext", "")))
print("PARSEDTEXT PREVIEW:")
print(data.get("parsedtext", "")[:1000])