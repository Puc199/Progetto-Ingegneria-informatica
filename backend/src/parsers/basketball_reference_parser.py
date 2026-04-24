import re
from src.parsers.base_parser import fetch_html, make_soup, extract_page_title, build_result


def parse_basketball_reference(url: str, html_text: str | None = None) -> dict:
    domain = "basketball-reference.com"

    if not html_text or html_text == "string":
        html_text = fetch_html(url)

    soup = make_soup(html_text)

    info = soup.find("div", id="info")

    title = ""
    if info:
        h1 = info.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)

    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
        else:
            title = extract_page_title(soup)

    paragraphs = []
    search_root = info if info else soup

    for p in search_root.find_all("p"):
        text = p.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        text = text.replace("▪", "").strip()
        if text:
            paragraphs.append(text)

    parsed_text = "\n\n".join(paragraphs).strip()

    return build_result(url, domain, title, html_text, parsed_text)