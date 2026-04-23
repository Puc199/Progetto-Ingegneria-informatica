import requests
from bs4 import BeautifulSoup


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; WebParser/1.0)"
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def extract_page_title(soup: BeautifulSoup) -> str:
    if soup.title:
        return soup.title.get_text(strip=True)
    return ""


def build_result(url: str, domain: str, title: str, htmltext: str, parsedtext: str) -> dict:
    return {
        "url": url,
        "domain": domain,
        "title": title,
        "htmltext": htmltext,
        "parsedtext": parsedtext,
    }