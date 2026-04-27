import re
from bs4 import BeautifulSoup, Comment
from src.parsers.base_parser import (
    fetch_html_crawl4ai,
    make_soup,
    extract_page_title,
    build_result,
)


def _clean_text(text: str) -> str:
    text = text.replace("▪", " ")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _uncomment_html_tables(soup: BeautifulSoup) -> BeautifulSoup:
    comments = soup.find_all(string=lambda t: isinstance(t, Comment))
    for comment in comments:
        raw = str(comment)
        if "<table" in raw or 'id="all_' in raw or "id='all_" in raw:
            try:
                parsed = BeautifulSoup(raw, "html.parser")
                comment.replace_with(parsed)
            except Exception:
                continue
    return soup


def _remove_noise(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup.find_all(["script", "style", "svg", "noscript"]):
        tag.decompose()
    return soup


def _extract_table_lines(table, max_rows: int = 8) -> list[str]:
    lines = []

    caption = table.find("caption")
    if caption:
        cap = _clean_text(caption.get_text(" ", strip=True))
        if cap:
            lines.append(f"### {cap}")

    rows = table.find_all("tr")
    for row in rows[:max_rows]:
        cells = row.find_all(["th", "td"])
        texts = []
        for cell in cells:
            text = _clean_text(cell.get_text(" ", strip=True))
            if text:
                texts.append(text)
        if texts:
            lines.append(" | ".join(texts))

    return lines


def _find_main_table(section):
    tables = section.find_all("table")
    if not tables:
        return None

    best = None
    best_score = -1

    for table in tables:
        rows = table.find_all("tr")
        score = len(rows)

        table_id = table.get("id", "")
        table_class = " ".join(table.get("class", []))

        if table_id:
            score += 5
        if "stats" in table_id.lower():
            score += 5
        if "stats_table" in table_class.lower():
            score += 3
        if table.find("caption"):
            score += 2

        if score > best_score:
            best_score = score
            best = table

    return best


def parse_basketball_reference(url: str, html_text: str | None = None) -> dict:
    domain = "basketball-reference.com"

    if not html_text or html_text == "string":
        html_text = fetch_html_crawl4ai(url)

    soup = make_soup(html_text)
    soup = _remove_noise(soup)
    soup = _uncomment_html_tables(soup)
    soup = _remove_noise(soup)

    info = soup.find("div", id="info")

    title = ""
    if info:
        h1 = info.find("h1")
        if h1:
            title = _clean_text(h1.get_text(" ", strip=True))
    if not title:
        title = extract_page_title(soup)

    parts = []

    if title:
        parts.append(f"# {title}")

    if info:
        meta = info.find("div", id="meta") or info
        for p in meta.find_all("p", recursive=False):
            text = _clean_text(p.get_text(" ", strip=True))
            if text:
                parts.append(text)

    wanted_sections = [
        ("all_per_game", "Per Game"),
        ("all_totals", "Totals"),
        ("all_advanced", "Advanced"),
        ("all_adj_shooting", "Adjusted Shooting"),
        ("all_playoffs_series", "Playoffs Series"),
        ("all_faq", "Frequently Asked Questions"),
    ]

    for section_id, fallback_heading in wanted_sections:
        section = soup.find("div", id=section_id)
        if not section:
            continue

        heading = section.find(["h2", "h3"])
        heading_text = fallback_heading
        if heading:
            maybe = _clean_text(heading.get_text(" ", strip=True))
            if maybe:
                heading_text = maybe

        parts.append(f"## {heading_text}")

        if section_id == "all_faq":
            faq_texts = []
            for node in section.find_all(["h3", "p"], limit=20):
                text = _clean_text(node.get_text(" ", strip=True))
                if text and text not in faq_texts:
                    faq_texts.append(text)
            parts.extend(faq_texts)
            continue

        table = _find_main_table(section)
        if table:
            parts.extend(_extract_table_lines(table, max_rows=8))

    parsed_text = "\n\n".join(x for x in parts if x).strip()


    print("TITLE:", title)
    print("PARSED PREVIEW:", parsed_text[:1200])
    print("PARSED LEN:", len(parsed_text))
    return build_result(url, domain, title, html_text, parsed_text)