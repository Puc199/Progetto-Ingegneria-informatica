from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Comment

from src.parsers.base_parser import (
    fetch_html_crawl4ai,
    make_soup,
    extract_page_title,
    build_result,
)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _dedupe_blocks(blocks: list[str]) -> list[str]:
    out = []
    seen = set()
    for block in blocks:
        norm = _normalize_text(block)
        if not norm:
            continue
        key = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(block.strip())
    return out


def _dedupe_lines(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines()]
    out = []
    seen = set()
    for line in lines:
        norm = _normalize_text(line)
        if not norm:
            continue
        key = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return "\n".join(out).strip()


def _remove_noise(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup.find_all(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()

    selectors = [
        "nav",
        "header",
        "footer",
        "aside",
        "#header",
        "#footer",
        "#nav",
        "#srcom",
        "#site_menu",
        "#footer_wrapper",
        ".footer",
        ".nav",
        ".breadcrumbs",
        ".ad-placeholder",
        ".advertisement",
        ".overlay",
        ".popup",
        ".cookie",
        ".cookies",
        ".sr_ad",
        ".promo",
    ]
    for selector in selectors:
        for tag in soup.select(selector):
            tag.decompose()

    for comment in soup.find_all(string=lambda x: isinstance(x, Comment)):
        comment.extract()

    return soup


def _guess_title(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.find("h1")
    if h1:
        txt = _normalize_text(h1.get_text(" ", strip=True))
        if txt:
            return txt

    title = soup.find("title")
    if title:
        txt = _normalize_text(title.get_text(" ", strip=True))
        if txt:
            return txt

    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        txt = _normalize_text(og.get("content", ""))
        if txt:
            return txt

    extracted = extract_page_title(soup)
    if extracted:
        extracted = _normalize_text(extracted)
        if extracted:
            return extracted

    return None


def _detect_branch(url: str, html: str) -> str:
    u = (url or "").lower()
    h = (html or "").lower()
    if "/playoffs/" in u or "playoffs series" in h or "series table" in h:
        return "playoff"
    if "/teams/" in u or "roster and stats" in h or "schedule and results" in h:
        return "team"
    if "/executives/" in u or "franchises" in h or "team records table" in h:
        return "executive"
    if "/players/" in u or "per game table" in h or "advanced table" in h:
        return "player"
    return "player"


def _table_caption(table) -> str:
    caption = table.find("caption")
    return _normalize_text(caption.get_text(" ", strip=True)) if caption else ""


def _table_to_text(table) -> str:
    parts = []
    caption = _table_caption(table)
    if caption:
        parts.append(caption)
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        row_text = [_normalize_text(cell.get_text(" ", strip=True)) for cell in cells]
        row_text = [x for x in row_text if x]
        if row_text:
            parts.append(" | ".join(row_text))
    return "\n".join(parts).strip()


def _extract_tables_from_visible_html(soup: BeautifulSoup) -> str:
    blocks = []
    for table in soup.find_all("table"):
        txt = _table_to_text(table)
        if txt:
            blocks.append(txt)
    return "\n\n".join(_dedupe_blocks(blocks)).strip()


def _extract_tables_from_comments(html: str) -> str:
    blocks = []
    outer = BeautifulSoup(html, "html.parser")
    for comment in outer.find_all(string=lambda x: isinstance(x, Comment)):
        comment_text = str(comment)
        if "<table" not in comment_text.lower():
            continue
        try:
            csoup = BeautifulSoup(comment_text, "html.parser")
        except Exception:
            continue
        for table in csoup.find_all("table"):
            txt = _table_to_text(table)
            if txt:
                blocks.append(txt)
    return "\n\n".join(_dedupe_blocks(blocks)).strip()


def _extract_text_from_node(node) -> str:
    if not node:
        return ""
    clone = BeautifulSoup(str(node), "html.parser")
    for bad in clone.select("script, style, noscript, table, svg, template"):
        bad.decompose()
    return _dedupe_lines(clone.get_text("\n", strip=True))


def _extract_body_text(soup: BeautifulSoup) -> str:
    body = soup.body
    if not body:
        return ""
    clone = BeautifulSoup(str(body), "html.parser")
    for bad in clone.select("script, style, noscript, nav, header, footer, aside, table, svg, template"):
        bad.decompose()
    return _dedupe_lines(clone.get_text("\n", strip=True))


def _extract_important_sections(soup: BeautifulSoup) -> str:
    parts = []
    seen = set()
    selectors = [
        "#meta",
        "#info",
        "#content",
        "#all_content",
        "main",
        "#div_per_game",
        "#div_totals",
        "#div_advanced",
        "#div_playoffs",
        "#div_roster",
        "#div_team_and_opponent",
        "#div_schedule",
        "#div_standings",
        "#div_team_records",
        "#div_franchises",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            text = _extract_text_from_node(node)
            if text:
                key = text.lower()
                if key not in seen:
                    seen.add(key)
                    parts.append(text)
    return "\n\n".join(parts).strip()


def parse_basketball_reference(
    url: str,
    html_text: Optional[str] = None,
    htmltext: Optional[str] = None,
    html: Optional[str] = None,
    raw_html: Optional[str] = None,
    content: Optional[str] = None,
    **kwargs,
):
    resolved_html = (
        html_text
        or htmltext
        or html
        or raw_html
        or content
        or kwargs.get("html_text")
        or kwargs.get("htmltext")
        or kwargs.get("html")
        or kwargs.get("raw_html")
        or kwargs.get("content")
    )

    if not resolved_html or resolved_html == "string":
        try:
            resolved_html = fetch_html_crawl4ai(url)
        except Exception:
            resolved_html = None

    domain = "basketball-reference.com"

    if not resolved_html:
        result = build_result(url, domain, None, None, "")
        result["branch"] = "player"
        return result

    soup = make_soup(resolved_html)
    soup = _remove_noise(soup)

    branch = _detect_branch(url, resolved_html)
    title = _guess_title(soup)

    parts = []

    if title:
        parts.append(title)

    meta_text = _extract_text_from_node(soup.select_one("#meta"))
    if meta_text:
        parts.append(meta_text)

    info_text = _extract_text_from_node(soup.select_one("#info"))
    if info_text:
        parts.append(info_text)

    important_sections = _extract_important_sections(soup)
    if important_sections:
        parts.append(important_sections)

    content_text = _extract_text_from_node(soup.select_one("#content"))
    if content_text:
        parts.append(content_text)

    visible_tables = _extract_tables_from_visible_html(soup)
    if visible_tables:
        parts.append(visible_tables)

    comment_tables = _extract_tables_from_comments(resolved_html)
    if comment_tables:
        parts.append(comment_tables)

    if not parts:
        body_text = _extract_body_text(soup)
        if body_text:
            parts.append(body_text)

    parts = _dedupe_blocks(parts)
    parsed_text = "\n\n".join(parts).strip()

    if not parsed_text:
        parsed_text = _dedupe_lines(soup.get_text("\n", strip=True))

    result = build_result(url, domain, title, resolved_html, parsed_text)
    result["branch"] = branch
    return result