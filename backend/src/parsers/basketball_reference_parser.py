from __future__ import annotations


import re
from typing import Optional


from bs4 import BeautifulSoup, Comment


from src.parsers.base_parser import fetch_html_crawl4ai, make_soup, extract_page_title, build_result



def _n(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()



def _dedupe_blocks(blocks):
    seen, out = set(), []
    for b in blocks:
        b = _n(b)
        if not b:
            continue
        k = b.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(b)
    return out



def _dedupe_lines(text: str) -> str:
    seen, out = set(), []
    for line in (text or "").splitlines():
        line = _n(line)
        if not line:
            continue
        k = line.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(line)
    return "\n".join(out).strip()



def _text(node) -> str:
    if not node:
        return ""
    clone = BeautifulSoup(str(node), "html.parser")
    for bad in clone.select("script, style, noscript, table, svg, template"):
        bad.decompose()
    return _dedupe_lines(clone.get_text("\n", strip=True))



def _strip_noise(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup.find_all(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    for sel in ["nav", "header", "footer", "aside", "#header", "#footer", "#nav", "#srcom", "#site_menu", "#footer_wrapper", ".footer", ".nav", ".breadcrumbs", ".ad-placeholder", ".advertisement", ".overlay", ".popup", ".cookie", ".cookies", ".sr_ad", ".promo"]:
        for tag in soup.select(sel):
            tag.decompose()
    return soup



def _guess_title(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.find("h1")
    if h1:
        t = _n(h1.get_text(" ", strip=True))
        if t:
            return t
    title = soup.find("title")
    if title:
        t = _n(title.get_text(" ", strip=True))
        if t:
            return t
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        t = _n(og["content"])
        if t:
            return t
    t = extract_page_title(soup)
    return _n(t) if t else None



def _visible_tables(soup: BeautifulSoup) -> str:
    blocks = []
    for table in soup.find_all("table"):
        lines = []
        cap = table.find("caption")
        if cap:
            ct = _n(cap.get_text(" ", strip=True))
            if ct:
                lines.append(ct)
        for tr in table.find_all("tr"):
            cells = [_n(x.get_text(" ", strip=True)) for x in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                lines.append(" | ".join(cells))
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(_dedupe_blocks(blocks)).strip()



def _comment_tables(html: str) -> str:
    outer = BeautifulSoup(html, "html.parser")
    blocks = []
    for c in outer.find_all(string=lambda x: isinstance(x, Comment)):
        txt = str(c)
        if "<table" not in txt.lower() and "stats_table" not in txt.lower():
            continue
        csoup = BeautifulSoup(txt, "html.parser")
        for table in csoup.find_all("table"):
            lines = []
            cap = table.find("caption")
            if cap:
                ct = _n(cap.get_text(" ", strip=True))
                if ct:
                    lines.append(ct)
            for tr in table.find_all("tr"):
                cells = [_n(x.get_text(" ", strip=True)) for x in tr.find_all(["th", "td"])]
                cells = [c for c in cells if c]
                if cells:
                    lines.append(" | ".join(cells))
            if lines:
                blocks.append("\n".join(lines))
    return "\n\n".join(_dedupe_blocks(blocks)).strip()



def _branch(url: str, html: str) -> str:
    u, h = (url or "").lower(), (html or "").lower()
    if "/playoffs/" in u:
        return "playoffs"
    if "/teams/" in u:
        return "teams"
    if "/executives/" in u:
        return "executives"
    if "/players/" in u:
        return "players"
    if "injury report" in h or "assistant coaches and staff" in h:
        return "teams"
    return "generic"



def _player(soup: BeautifulSoup, html: str):
    parts = []
    for sel in ["#meta", "#info", "#content", "#div_transactions", "#div_faq", "#div_translations"]:
        t = _text(soup.select_one(sel))
        if t:
            parts.append(t)
    for sel in ["#div_per_game", "#div_totals", "#div_advanced", "#div_shooting", "#div_adj_shooting", "#div_playoffs_per_game", "#div_playoffs_advanced", "#div_all_sims"]:
        for node in soup.select(sel):
            t = _text(node)
            if t:
                parts.append(t)
    return parts



def _playoffs(soup: BeautifulSoup, html: str):
    parts = []
    for sel in ["#content", "#meta", "#all_games", "#all_series", "#all_playoffs"]:
        t = _text(soup.select_one(sel))
        if t:
            parts.append(t)
    return parts



def _teams(soup: BeautifulSoup, html: str):
    parts = []
    for sel in ["#meta", "#content", "#all_roster", "#all_injury_report", "#all_staff", "#all_schedule"]:
        t = _text(soup.select_one(sel))
        if t:
            parts.append(t)
    return parts



def _executives(soup: BeautifulSoup, html: str):
    parts = []
    for sel in ["#meta", "#content", "#all_franchises", "#all_awards", "#all_transactions", "#all_draft_picks"]:
        t = _text(soup.select_one(sel))
        if t:
            parts.append(t)
    return parts



def parse_basketball_reference(url: str, html_text: Optional[str] = None, html: Optional[str] = None, raw_html: Optional[str] = None, content: Optional[str] = None, **kwargs):
    resolved = html_text or html or raw_html or content or kwargs.get("html_text") or kwargs.get("html") or kwargs.get("raw_html") or kwargs.get("content")
    if not resolved or resolved == "string":
        try:
            resolved = fetch_html_crawl4ai(url)
        except Exception:
            resolved = None


    domain = "www.basketball-reference.com"
    if not resolved:
        res = build_result(url, domain, None, None, "")
        res["branch"] = "generic"
        return res


    soup = make_soup(resolved)
    soup = _strip_noise(soup)
    title = _guess_title(soup)
    br = _branch(url, resolved)


    if br == "players":
        parts = _player(soup, resolved)
    elif br == "playoffs":
        parts = _playoffs(soup, resolved)
    elif br == "teams":
        parts = _teams(soup, resolved)
    elif br == "executives":
        parts = _executives(soup, resolved)
    else:
        parts = []
        for sel in ["#meta", "#content"]:
            t = _text(soup.select_one(sel))
            if t:
                parts.append(t)


    parts = _dedupe_blocks(parts)
    parsed = "\n\n".join(parts).strip()
    if not parsed:
        parsed = _dedupe_lines(soup.get_text("\n", strip=True))


    res = build_result(url, domain, title, resolved, parsed)
    res["branch"] = br
    return res
