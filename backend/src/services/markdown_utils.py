import re
import mistune
from bs4 import BeautifulSoup


def remove_markdown(text: str) -> str:
    if not text:
        return ""

    html = mistune.html(text)
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(True):
        tag.unwrap()

    plain = str(soup)
    plain = re.sub(r"[ \t]+", " ", plain)
    plain = re.sub(r"\n+", "\n", plain)

    return plain.strip()