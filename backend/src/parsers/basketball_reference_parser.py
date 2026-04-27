import re
from bs4 import BeautifulSoup, Comment
from src.parsers.base_parser import (
    fetch_html_crawl4ai,
    parse_raw_html_with_crawl4ai,
    make_soup,
    extract_page_title,
    build_result,
)

def _uncomment_html_tables(soup: BeautifulSoup) -> BeautifulSoup:
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        content = str(comment)
        if "<table" in content or 'div id="all_' in content:
            try:
                parsed = BeautifulSoup(content, "html.parser")
                comment.replace_with(parsed)
            except Exception:
                continue
    return soup

def _clean_text(text: str) -> str:
    text = text.replace("▪", " ")
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def parse_basketball_reference(url: str, html_text: str | None = None) -> dict:
    domain = "basketball-reference.com"

    if not html_text or html_text == "string":
        html_text = fetch_html_crawl4ai(url)
    else:
        html_text = parse_raw_html_with_crawl4ai(html_text)

    soup = make_soup(html_text)
    soup = _uncomment_html_tables(soup)

    info = soup.find("div", id="info")

    title = ""
    if info and info.find("h1"):
        title = _clean_text(info.find("h1").get_text(" ", strip=True))
    elif soup.find("h1"):
        title = _clean_text(soup.find("h1").get_text(" ", strip=True))
    else:
        title = extract_page_title(soup)

    parts = []

    if title:
        parts.append(f"# {title}")

    if info:
        for p in info.find_all("p"):
            text = _clean_text(p.get_text(" ", strip=True))
            if text:
                parts.append(text)

    content = soup.find("div", id="content") or soup

    seen_headers = set()
    for header in content.find_all(["h2", "h3"], limit=12):
        text = _clean_text(header.get_text(" ", strip=True))
        if text and text.lower() not in seen_headers:
            parts.append(f"## {text}")
            seen_headers.add(text.lower())

    for table in content.find_all("table", limit=6):
        caption = table.find("caption")
        if caption:
            cap = _clean_text(caption.get_text(" ", strip=True))
            if cap:
                parts.append(f"### {cap}")

        rows = table.find_all("tr")[:6]
        for row in rows:
            cells = row.find_all(["th", "td"])
            cell_texts = [_clean_text(c.get_text(" ", strip=True)) for c in cells]
            cell_texts = [c for c in cell_texts if c]
            if cell_texts:
                parts.append("- " + " | ".join(cell_texts))

    parsed_text = "\n\n".join(part for part in parts if part).strip()

    return build_result(url, domain, title, html_text, parsed_text)