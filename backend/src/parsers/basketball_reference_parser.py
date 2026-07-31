"""
Parser dedicato per il dominio basketball-reference.com

Problemi risolti rispetto alla versione precedente
--------------------------------------------------
1. Le tabelle di Basketball-Reference sono nascoste dentro COMMENTI HTML:
       <div class="placeholder"></div>
       <!-- <div class="table_container" id="div_per_game"><table>...</table></div> -->
   Il sito le "scommenta" via JavaScript lato browser. Su HTML statico
   (quello salvato nel Gold Standard) BeautifulSoup non le vede affatto.
   -> _uncomment_hidden_content() le reinserisce nel DOM prima del parsing.

2. Il vecchio _text() faceva decompose() su tutti i <table>: anche le poche
   tabelle visibili venivano buttate via -> recall bassissima.

3. I selettori erano hard-coded per id (#div_per_game, #all_roster, ...) ma
   gli id cambiano da pagina a pagina (#div_per_game su /players/,
   #div_per_game_stats su /teams/) -> molte sezioni non venivano trovate.
   -> ora si usa un walker strutturale generico sui wrapper div[id^="all_"].

4. #content veniva preso in blocco INSIEME a #meta: menu, footer, sponsor,
   "Share & Export", liste di link finivano nel parsed_text -> precision bassa.
   -> ora c'è una whitelist strutturale + filtro riga per riga.

5. L'output non era Markdown, mentre la specifica lo richiede esplicitamente.
   -> ora: # titolo, ## sezioni, - bullet per il meta, tabelle Markdown.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from src.parsers.base_parser import fetch_html_crawl4ai, make_soup, build_result


# --------------------------------------------------------------------------- #
# Configurazione (usata da tools/tune_br.py per la messa a punto sul GS)
# --------------------------------------------------------------------------- #

INCLUDE_TABLES = True      # includere le tabelle statistiche come tabelle Markdown
MAX_TABLE_ROWS = 0         # 0 = nessun limite sul numero di righe per tabella
INCLUDE_TABLE_HEADERS = True


# --------------------------------------------------------------------------- #
# Rumore
# --------------------------------------------------------------------------- #

NOISE_SELECTORS = [
    # tecnici
    "script", "style", "noscript", "svg", "template", "iframe", "form",
    "button", "select", "input", "link[rel=stylesheet]",
    # header / navigazione del sito
    "#header", "#header_holder", "#site_menu", "#full_site_menu",
    "#site_menu_link", "#inpage_nav", ".inpage_nav", "#subnav", "#nav",
    "nav", "header", ".breadcrumbs", "#breadcrumbs", ".sr_nav", "#sr_nav",
    # footer
    "footer", "#footer", "#footer_wrapper", "#bottom_nav",
    "#bottom_nav_container", "#sr_footer", ".sr-footer", ".footer_bottom",
    # pubblicità / sponsor / overlay
    "#leaderboard", ".leaderboard", "[id^=leaderboard]", "[id^=div_ad]",
    "[id*=advert]", ".ad", ".ads", ".adsbygoogle", ".sr_ad",
    ".ad-placeholder", ".advertisement", ".overlay", ".popup", ".modal",
    ".cookie", ".cookies", ".promo", ".sponsor",
    # UI delle tabelle (Share & Export, Glossary, filtri stagione, tooltip)
    ".section_heading_text", "[id^=tfooter_]", ".table_outer_container .footer",
    ".filter", ".hoversmooth", ".tooltip", "#tooltip", ".hidden_hover",
    ".shareon", ".share", ".sr-copy", ".prevnext", ".media-item",
    # blocchi "More ... Pages" e link correlati
    "#all_button_menu", ".button2", ".sr_preset",
]

# Wrapper (div[id^="all_"]) da saltare del tutto: id che matchano questi pattern
SKIP_WRAPPER_ID = re.compile(
    r"(leaderboard|advert|_ad$|sponsor|footer|social|nav|button|marketing)",
    re.IGNORECASE,
)

# Righe da scartare: rumore testuale ricorrente su Sports Reference
NOISE_LINE_PATTERNS = [
    r"^welcome\b.*your account",
    r"^log\s?(in|out)\b",
    r"^ad[- ]free",
    r"^create account",
    r"^subscribe\b",
    r"^sign up\b",
    r"^full site menu",
    r"^we'?re hiring",
    r"^do you have a sports website",
    r"^question,? comment,? feedback",
    r"^are you a stathead",
    r"^stathead\b",
    r"^get your first month free",
    r"^much of the play-by-play",
    r"^all logos are the trademark",
    r"^copyright ©",
    r"^data provided by",
    r"^sports reference\b",
    r"^site last updated",
    r"^share & export",
    r"^embed this",
    r"^view as table",
    r"^glossary$",
    r"^modify, export",
    r"^switch to\b",
    r"^more .* pages$",
    r"^you are here",
    r"^in the news",
    r"^all-time greats",
    r"^active greats",
    r"^every sports reference social media account",
    r"^our reasoning for presenting",
    r"^\W*$",
]
NOISE_LINE_RE = re.compile("|".join(NOISE_LINE_PATTERNS), re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Utility di testo
# --------------------------------------------------------------------------- #

def _n(s: Optional[str]) -> str:
    """Normalizza gli spazi bianchi."""
    s = (s or "").replace("\xa0", " ").replace("\u200b", "")
    s = s.replace("▪", " ")
    return re.sub(r"\s+", " ", s).strip()


def _clean_line(s: str) -> str:
    s = _n(s)
    s = re.sub(r"\s+([,.;:!?%])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    return s.strip()


def _keep_line(s: str) -> bool:
    if len(s) < 2:
        return False
    if NOISE_LINE_RE.search(s):
        return False
    return True


def _cell_text(cell: Tag) -> str:
    txt = _n(cell.get_text(" ", strip=True))
    return txt.replace("|", "\\|")


# --------------------------------------------------------------------------- #
# 1. Scommentare il contenuto nascosto (il fix principale)
# --------------------------------------------------------------------------- #

def _uncomment_hidden_content(soup: BeautifulSoup, passes: int = 2) -> int:
    """
    Basketball-Reference nasconde quasi tutte le tabelle dentro commenti HTML.
    Qui i commenti che contengono markup vengono ri-parsati e reinseriti nel DOM.
    Ritorna il numero di commenti espansi (utile per il debug).
    """
    total = 0
    for _ in range(passes):
        comments = soup.find_all(string=lambda s: isinstance(s, Comment))
        expanded = 0
        for comment in comments:
            raw = str(comment)
            if "<table" not in raw and "table_container" not in raw:
                continue
            fragment = BeautifulSoup(raw, "html.parser")
            anchor = comment
            for child in list(fragment.contents):
                anchor.insert_after(child)
                anchor = child
            comment.extract()
            expanded += 1
        total += expanded
        if expanded == 0:
            break
    return total


def _strip_noise(soup: BeautifulSoup) -> BeautifulSoup:
    for selector in NOISE_SELECTORS:
        try:
            for tag in soup.select(selector):
                tag.decompose()
        except Exception:
            continue
    # commenti residui (non contenenti tabelle)
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    return soup


# --------------------------------------------------------------------------- #
# 2. Titolo e dominio
# --------------------------------------------------------------------------- #

def _extract_title(soup: BeautifulSoup) -> str:
    """Attenzione: va chiamata PRIMA di _strip_noise (che rimuove #header)."""
    for selector in ("#meta h1", "#info h1", "#content h1", "h1"):
        node = soup.select_one(selector)
        if node:
            title = _n(node.get_text(" ", strip=True))
            if title:
                return title
    if soup.title:
        title = _n(soup.title.get_text())
        title = re.sub(r"\s*[|\-–]\s*Basketball[- ]?Reference\.com.*$", "", title, flags=re.I)
        return title.strip()
    return ""


def _extract_domain(url: str) -> str:
    host = (urlparse(url or "").hostname or "basketball-reference.com").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _branch(url: str, html: str) -> str:
    """Mantenuto per retro-compatibilità / debug: il parsing NON dipende da questo."""
    u = (url or "").lower()
    for key in ("playoffs", "teams", "executives", "players", "coaches",
                "leagues", "awards", "boxscores", "draft"):
        if f"/{key}/" in u:
            return key
    return "generic"


# --------------------------------------------------------------------------- #
# 3. Rendering Markdown
# --------------------------------------------------------------------------- #

def _render_meta(meta: Tag) -> list[str]:
    """#meta contiene la bio del giocatore / la scheda della squadra."""
    lines: list[str] = []
    info = meta.select_one("#info") or meta
    for p in info.find_all("p"):
        text = _clean_line(p.get_text(" ", strip=True))
        if _keep_line(text):
            lines.append(f"- {text}")
    return lines


def _table_header(table: Tag) -> list[str]:
    thead = table.find("thead")
    if not thead:
        return []
    rows = [tr for tr in thead.find_all("tr")
            if "over_header" not in (tr.get("class") or [])]
    if not rows:
        return []
    return [_cell_text(c) for c in rows[-1].find_all(["th", "td"])]


def _table_body_rows(table: Tag) -> Iterable[list[str]]:
    containers = table.find_all(["tbody", "tfoot"]) or [table]
    for container in containers:
        for tr in container.find_all("tr"):
            classes = tr.get("class") or []
            if any(c in classes for c in ("thead", "over_header", "spacer",
                                          "partial_table", "hidden")):
                continue
            cells = [_cell_text(c) for c in tr.find_all(["th", "td"])]
            if any(cells):
                yield cells


def _render_table(table: Tag) -> str:
    """Converte una tabella HTML in tabella Markdown."""
    header = _table_header(table) if INCLUDE_TABLE_HEADERS else []
    rows = list(_table_body_rows(table))
    if MAX_TABLE_ROWS:
        rows = rows[:MAX_TABLE_ROWS]
    if not rows:
        return ""

    width = max([len(header)] + [len(r) for r in rows])
    if not header:
        header = [""] * width
    header = header + [""] * (width - len(header))

    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join(["---"] * width) + " |"]
    for row in rows:
        row = row + [""] * (width - len(row))
        out.append("| " + " | ".join(row) + " |")

    caption = table.find("caption")
    if caption:
        cap = _clean_line(caption.get_text(" ", strip=True))
        if _keep_line(cap):
            out.insert(0, f"**{cap}**")
    return "\n".join(out)


def _render_wrapper(wrapper: Tag) -> list[str]:
    """Renderizza un blocco div[id^='all_'] (intestazione + testo + tabelle)."""
    blocks: list[str] = []

    heading_node = wrapper.select_one(".section_heading h2, .section_heading h3, h2, h3")
    if heading_node:
        heading = _clean_line(heading_node.get_text(" ", strip=True))
        if _keep_line(heading):
            level = 2 if heading_node.name == "h2" else 3
            blocks.append(f"{'#' * level} {heading}")

    for p in wrapper.find_all(["p", "li"]):
        if p.find_parent("table") is not None:
            continue
        text = _clean_line(p.get_text(" ", strip=True))
        if _keep_line(text) and len(text) > 3:
            blocks.append(text if p.name == "p" else f"- {text}")

    if INCLUDE_TABLES:
        for table in wrapper.find_all("table"):
            rendered = _render_table(table)
            if rendered:
                blocks.append(rendered)

    return blocks


def _iter_sections(content: Tag) -> Iterable[Tag]:
    """
    Wrapper di sezione in ordine di documento, senza duplicare i nidificati.
    Copre players / teams / playoffs / executives / coaches / leagues.
    """
    processed: list[Tag] = []
    selector = 'div[id^="all_"], div.table_wrapper, div.section_wrapper, div.overthrow'
    for wrapper in content.select(selector):
        wid = wrapper.get("id") or ""
        if wid and SKIP_WRAPPER_ID.search(wid):
            continue
        if any(prev is not wrapper and prev in wrapper.parents for prev in processed):
            continue
        processed.append(wrapper)
        yield wrapper


def _fallback_blocks(content: Tag) -> list[str]:
    """Usato solo se la struttura standard non viene riconosciuta."""
    blocks: list[str] = []
    for node in content.find_all(["h2", "h3", "p", "table"]):
        if node.name == "table":
            if INCLUDE_TABLES:
                rendered = _render_table(node)
                if rendered:
                    blocks.append(rendered)
            continue
        if node.find_parent("table") is not None:
            continue
        text = _clean_line(node.get_text(" ", strip=True))
        if not _keep_line(text):
            continue
        if node.name in ("h2", "h3"):
            blocks.append(f"{'#' * (2 if node.name == 'h2' else 3)} {text}")
        elif len(text) > 3:
            blocks.append(text)
    return blocks


def _finalize(blocks: list[str]) -> str:
    """Deduplica le righe (le righe di tabella restano intatte) e compatta."""
    seen: set[str] = set()
    out: list[str] = []
    for block in blocks:
        block = block.strip("\n")
        if not block:
            continue
        kept: list[str] = []
        for line in block.split("\n"):
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("|"):           # riga di tabella: mai deduplicata
                kept.append(line)
                continue
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            kept.append(line)
        if kept:
            out.append("\n".join(kept))
    text = "\n\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --------------------------------------------------------------------------- #
# 4. Entry point
# --------------------------------------------------------------------------- #

def parse_basketball_reference(
    url: str,
    html_text: Optional[str] = None,
    htmltext: Optional[str] = None,
    html: Optional[str] = None,
    raw_html: Optional[str] = None,
    content: Optional[str] = None,
    **kwargs,
) -> dict:
    resolved = (
        html_text or htmltext or html or raw_html or content
        or kwargs.get("html_text") or kwargs.get("htmltext")
        or kwargs.get("html") or kwargs.get("raw_html") or kwargs.get("content")
    )
    if not resolved or not str(resolved).strip() or str(resolved).strip() == "string":
        resolved = fetch_html_crawl4ai(url)

    domain = _extract_domain(url)

    if not resolved:
        result = build_result(url, domain, "", "", "")
        result["branch"] = "generic"
        return result

    soup = make_soup(resolved)

    # 1) contenuto nascosto nei commenti -> DOM  (il fix decisivo)
    uncommented = _uncomment_hidden_content(soup)

    # 2) titolo prima di rimuovere il rumore
    title = _extract_title(soup)

    # 3) pulizia
    _strip_noise(soup)

    content_root = soup.select_one("#content") or soup.body or soup

    blocks: list[str] = []
    if title:
        blocks.append(f"# {title}")

    meta = content_root.select_one("#meta")
    if meta:
        meta_lines = _render_meta(meta)
        if meta_lines:
            blocks.append("\n".join(meta_lines))   # lista Markdown unica
        meta.decompose()          # evita che venga riletto come sezione

    section_blocks: list[str] = []
    for wrapper in _iter_sections(content_root):
        section_blocks.extend(_render_wrapper(wrapper))

    if not section_blocks:
        section_blocks = _fallback_blocks(content_root)

    blocks.extend(section_blocks)

    parsed_text = _finalize(blocks)

    result = build_result(url, domain, title, resolved, parsed_text)
    result["branch"] = _branch(url, resolved)
    result["_uncommented_blocks"] = uncommented    # solo debug, ignorato dall'API
    return result
