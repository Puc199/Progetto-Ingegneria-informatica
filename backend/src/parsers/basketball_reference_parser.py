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

# Le tabelle vanno incluse o no a seconda del tipo di pagina, perche' il GS di
# questo progetto le esclude sulle schede giocatore ma le include altrove
# (tabellone dei playoff, roster di squadra, ...).
TABLES_BY_BRANCH = {
    "players": False,
    "playoffs": True,
    "teams": True,
    "executives": True,
    "coaches": True,
    "leagues": True,
    "awards": True,
    "draft": True,
    "boxscores": True,
    "generic": False,
}
DEFAULT_INCLUDE_TABLES = False

# Su alcune pagine solo una parte delle tabelle e' contenuto informativo.
# Sulle pagine di serie playoff il GS contiene i riepiloghi partita
# (div.game_summary) ma non le tabelle Advanced Stats / Four Factors.
# Se il selettore non trova nulla nella pagina, si ricade su tutte le tabelle.
TABLE_SCOPE_BY_BRANCH = {
    "playoffs": [".game_summary", ".game_summaries"],
    # sulle pagine squadra il GS contiene il riquadro riepilogativo, il roster,
    # l'injury report e lo staff tecnico: non le tabelle statistiche
    # (Salaries / Per Game / Advanced / Shooting).
    # I selettori con [id*=...] reggono le variazioni di nome fra le stagioni.
    "teams": ["#all_roster", "#div_roster",
              "[id*='injur']", "[id*='coach']"],
}

INCLUDE_TABLES = None      # None = decidi in base al branch; True/False = forza
MAX_TABLE_ROWS = 0         # 0 = nessun limite sul numero di righe per tabella
INCLUDE_TABLE_HEADERS = True


def _tables_enabled(branch: str) -> bool:
    if INCLUDE_TABLES is not None:
        return bool(INCLUDE_TABLES)
    return TABLES_BY_BRANCH.get(branch, DEFAULT_INCLUDE_TABLES)


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
    ".f-i",                     # iconcine bandiera: producono testo "us", "vi", "br"
    ".shareon", ".share", ".sr-copy", ".prevnext", ".media-item",
    # blocchi "More ... Pages" e link correlati
    "#all_button_menu", ".button2", ".sr_preset",
]

# Wrapper (div[id^="all_"]) da saltare del tutto: id che matchano questi pattern
SKIP_WRAPPER_ID = re.compile(
    r"(leaderboard|advert|_ad$|sponsor|footer|social|nav|button|marketing"
    r"|news|nba_stats|stats_nba|linescore)",
    re.IGNORECASE,
)

# Sezioni da saltare in base al TITOLO: sono blocchi di link o feed di notizie,
# non contenuto della pagina. Piu' affidabile degli id, che cambiano spesso.
SKIP_SECTION_HEADING = re.compile(
    r"^(player news|view on stats\.nba\.com|in the news|more \S.* pages"
    r"|other resources|frivolities|sponsor|welcome)",
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
    r"^upgraded$",
    r"^player front$",
    r"^you are here",
    r"^in the news",
    r"^all-time greats",
    r"^active greats",
    r"^every sports reference social media account",
    r"^our reasoning for presenting",
    r"^\W*$",
]
NOISE_LINE_RE = re.compile("|".join(NOISE_LINE_PATTERNS), re.IGNORECASE)

# Un commento HTML viene espanso se contiene markup di contenuto
MARKUP_RE = re.compile(r"<(table|div|p|ul|ol|dl|tbody|tr|h[1-6])\b", re.IGNORECASE)

# Tag "a blocco" da cui estrarre il testo dentro una sezione
TEXT_TAGS = ["p", "li", "dt", "dd", "h3", "h4", "h5"]


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
    # separatore vuoto: con " " markup tipo <a>J. Butler</a>-MIA diventerebbe
    # "J. Butler -MIA" e <strong>F</strong>inal diventerebbe "F inal"
    txt = _n(cell.get_text(""))
    return txt.replace("|", "\\|")


# --------------------------------------------------------------------------- #
# 1. Scommentare il contenuto nascosto (il fix principale)
# --------------------------------------------------------------------------- #

def _uncomment_hidden_content(soup: BeautifulSoup, passes: int = 2) -> int:
    """
    Basketball-Reference nasconde nei commenti HTML non solo le tabelle
    statistiche, ma anche transactions, FAQ, translations e altre sezioni
    testuali. Qui ogni commento che contiene markup viene ri-parsato e
    reinserito nel DOM. Ritorna il numero di commenti espansi (debug).
    """
    total = 0
    for _ in range(passes):
        comments = soup.find_all(string=lambda s: isinstance(s, Comment))
        expanded = 0
        for comment in comments:
            raw = str(comment)
            if "<script" in raw.lower() or "[if " in raw.lower():
                continue
            if not MARKUP_RE.search(raw):
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


def _strip_minimal(soup: BeautifulSoup) -> BeautifulSoup:
    """Pulizia conservativa: solo tag tecnici. Usata come paracadute."""
    for tag in soup.find_all(["script", "style", "noscript", "svg", "template", "iframe", "form"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    return soup


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


# Deve coincidere ESATTAMENTE con la voce in domains.json e con il campo
# "domain" delle entry del Gold Standard.
CANONICAL_DOMAIN = "www.basketball-reference.com"


def _extract_domain(url: str) -> str:
    return CANONICAL_DOMAIN


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

def _lines_from(node: Tag, tags: list[str]) -> list[str]:
    """Testo dei tag a blocco, saltando quello che sta dentro le tabelle."""
    lines: list[str] = []
    for el in node.find_all(tags):
        if el.find_parent("table") is not None:
            continue
        if el.find(tags) is not None:        # contenitore: lo gestiscono i figli
            continue
        text = _clean_line(el.get_text(" ", strip=True))
        if _keep_line(text):
            lines.append(text)
    return lines


def _fallback_lines(node: Tag) -> list[str]:
    """Ultima spiaggia: testo grezzo della sezione, tabelle escluse."""
    clone = BeautifulSoup(str(node), "html.parser")
    for table in clone.find_all("table"):
        table.decompose()
    lines: list[str] = []
    for raw in clone.get_text("\n", strip=True).split("\n"):
        text = _clean_line(raw)
        if _keep_line(text):
            lines.append(text)
    return lines


def _render_meta(meta: Tag) -> list[str]:
    """
    #meta contiene la bio (in <p>) e la bacheca dei premi (<ul id="bling">
    con dei <li>): servono entrambi, il GS li include tutti e due.
    Si legge tutto #meta e non solo #info, perche' su alcune pagine il bling
    sta fuori da #info (la foto e' gia' stata rimossa come rumore).
    """
    info = meta
    lines = _lines_from(info, ["p", "li"])
    if not lines:
        lines = _fallback_lines(info)
    return [f"- {line}" for line in lines]


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

    # la <caption> di Basketball-Reference e' testo dell'interfaccia
    # ("Roster Table", "Per Game Table"), non contenuto della pagina
    return "\n".join(out)


def _allowed_tables(content: Tag, branch: str) -> Optional[set[int]]:
    """id() delle tabelle ammesse, o None se sono ammesse tutte."""
    selectors = TABLE_SCOPE_BY_BRANCH.get(branch)
    if not selectors:
        return None
    allowed = {
        id(table)
        for selector in selectors
        for node in content.select(selector)
        for table in node.find_all("table")
    }
    return allowed or None          # nessun match: nessuna restrizione


def _render_wrapper(wrapper: Tag, include_tables: bool,
                    allowed: Optional[set[int]] = None) -> list[str]:
    """Renderizza un blocco div[id^='all_'] (intestazione + testo + tabelle)."""
    blocks: list[str] = []

    heading_node = wrapper.select_one(".section_heading h2, .section_heading h3, h2, h3")
    heading_text = ""
    if heading_node:
        candidate = _clean_line(heading_node.get_text(" ", strip=True))
        if SKIP_SECTION_HEADING.match(candidate):
            return []
        if _keep_line(candidate):
            heading_text = f"{'#' * (2 if heading_node.name == 'h2' else 3)} {candidate}"

    lines = _lines_from(wrapper, TEXT_TAGS)
    if not lines and not wrapper.find("table"):
        lines = _fallback_lines(wrapper)
    for line in lines:
        if heading_node is not None and line == _clean_line(heading_node.get_text(" ", strip=True)):
            continue
        if len(line) > 3:
            blocks.append(line)

    if include_tables:
        for table in wrapper.find_all("table"):
            if allowed is not None and id(table) not in allowed:
                continue
            rendered = _render_table(table)
            if rendered:
                blocks.append(rendered)

    # l'intestazione si emette solo se la sezione ha davvero del contenuto:
    # con INCLUDE_TABLES=False evita decine di "## Per Game" a vuoto
    if heading_text and blocks:
        blocks.insert(0, heading_text)
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


def _fallback_blocks(content: Tag, include_tables: bool) -> list[str]:
    """Usato solo se la struttura standard non viene riconosciuta."""
    blocks: list[str] = []
    for node in content.find_all(["h2", "h3", "p", "table"]):
        if node.name == "table":
            if include_tables:
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

def _collect(soup: BeautifulSoup, branch: str, include_tables: bool,
             aggressive: bool) -> list[str]:
    """Estrae meta + sezioni. aggressive=False applica solo la pulizia minima."""
    _strip_noise(soup) if aggressive else _strip_minimal(soup)

    content_root = soup.select_one("#content") or soup.body or soup

    blocks: list[str] = []
    meta = content_root.select_one("#meta") or soup.select_one("#meta")
    if meta:
        meta_lines = _render_meta(meta)
        if meta_lines:
            blocks.append("\n".join(meta_lines))
        meta.decompose()          # evita che venga riletto come sezione

    allowed = _allowed_tables(content_root, branch) if include_tables else None

    sections: list[str] = []
    for wrapper in _iter_sections(content_root):
        sections.extend(_render_wrapper(wrapper, include_tables, allowed))
    if not sections:
        sections = _fallback_blocks(content_root, include_tables)

    blocks.extend(sections)
    return blocks


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

    # 2) titolo e bacheca dei premi PRIMA di rimuovere il rumore
    title = _extract_title(soup)

    # <ul id="bling">: su alcune pagine sta fuori da #meta, va preso a parte
    bling_lines: list[str] = []
    bling = soup.select_one("#bling")
    if bling:
        for item in bling.find_all("li"):
            text = _clean_line(item.get_text(" ", strip=True))
            if _keep_line(text):
                bling_lines.append(f"- {text}")

    # 3) pulizia
    _strip_noise(soup)

    branch = _branch(url, resolved)
    include_tables = _tables_enabled(branch)

    body = _collect(soup, branch, include_tables, aggressive=True)

    # Paracadute: se la pulizia aggressiva ha svuotato la pagina (selettori di
    # rumore troppo larghi su una variante di markup), si riparte da capo con
    # una pulizia minima. Meglio un po' di rumore che una pagina vuota.
    if not body:
        retry = make_soup(resolved)
        _uncomment_hidden_content(retry)
        body = _collect(retry, branch, include_tables, aggressive=False)

    blocks: list[str] = []
    if title:
        blocks.append(f"# {title}")
    if bling_lines:
        blocks.append("\n".join(bling_lines))
    blocks.extend(body)

    parsed_text = _finalize(blocks)

    result = build_result(url, domain, title, resolved, parsed_text)
    result["branch"] = branch
    result["_uncommented_blocks"] = uncommented    # solo debug, ignorato dall'API
    return result
