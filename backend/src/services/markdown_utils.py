import re
import mistune
from bs4 import BeautifulSoup


def remove_markdown(text: str) -> str:
    if not text:
        return ""

    html = mistune.markdown(text)
    soup = BeautifulSoup(html, "html.parser")
    plain = soup.get_text(separator=" ", strip=True)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain