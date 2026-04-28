import requests

url = "https://www.basketball-reference.com/players/j/jamesle01.html"
html_text = requests.get(url).text

print(html_text[:1000])