import re
from bs4 import Tag
from src.parsers.base_parser import (
    BaseParser,
    build_result,
    extract_page_title,
    fetch_html,
    make_soup,
)


STOP_HEADINGS = {
    #Italiano
    "note",
    "note e riferimenti",
    "riferimenti",
    "bibliografia",
    "altri progetti",
    "collegamenti esterni",
    "voci correlate",
    "vedi anche",
    "navigazione",
    "pagine correlate",
    "controllo di autorità",
    "wikisource",
    "wikiquote",
    "wikizionario",
    "wikinotizie",
    "portale",
    "categorie",

    # English
    "notes",
    "references",
    "bibliography",
    "further reading",
    "external links",
    "see also",
    "navigation",
    "related pages",
    "authority control",
    "portal",
    "categories",
    "sister projects",
    "wikisource",
    "wikiquote",
    "wiktionary",
    "wikinews",
    "wikibooks",
    "wikiversity",
    "wikivoyage",
    "wikimedia commons",
    "commons"
}


REMOVE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "table",
    "figure",
    "img",
    "math",
    "sup.reference",
    ".reference",
    ".reflist",
    ".mw-references-wrap",
    ".navbox",
    ".vertical-navbox",
    ".metadata",
    ".infobox",
    ".sinottico",
    ".toc",
    "#toc",
    ".hatnote",
    ".mw-editsection",
    ".noprint",
    ".nomobile",
    ".thumb",
    ".gallery",
    ".gallerybox",
    ".sidebar",
    ".ambox",
    ".ombox",
    ".tmbox",
    ".fmbox",
    ".dmbox",
    ".plainlinks",
    ".sistersitebox",
    ".mw-authority-control",
    ".catlinks",
    ".vector-header-container",
    ".vector-page-toolbar",
    ".vector-column-start",
    ".vector-column-end",
    "#mw-navigation",
    "#siteNotice",
    "#footer",
    ".interlanguage-link",
    ".mw-indicator",
    "[class*='mw-editsection']",
    "[class*='editsection']",
]


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\[[0-9]+\]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]])", r"\1", text)
    text = re.sub(r"\.\.\.+", "...", text)
    return text.strip()


def clean_output(text: str) -> str:
    text = text.replace("\xa0", " ")

    noise_patterns = [
        r"relmw[A-Za-z]+",
        r"typeofmw[A-Za-z]+",
        r"idmw[A-Za-z0-9]+",
        r"aboutmwt\d+",
        r"data-mw[a-zA-Z0-9\-.:]*",
        r"mw[-A-Za-z0-9_:.]+",
        r"citeref[-A-Za-z0-9_:.]+",
        r"citenote[-A-Za-z0-9_:.]+",
        r"ooui-php-\d+",
        r"mw-content-ltr",
        r"mw-parser-output",
        r"mw-editsection",
    ]

    for pattern in noise_patterns:
        text = re.sub(pattern, " ", text)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]

    cleaned = []
    for line in lines:
        low = line.lower()

        if len(line) < 2:
            continue
        if "modifica wikitesto" in low:
            continue
        if "modifica la sezione" in low:
            continue
        if low == "modifica":
            continue
        if low.startswith("coordinate"):
            continue
        if "usa l'anteprima" in low:
            continue
        if low.startswith("wikipedia:"):
            continue
        if "pagine correlate" in low:
            continue
        if "controllo di autorità" in low:
            continue

        cleaned.append(line)

    return "\n\n".join(cleaned).strip()


def heading_level(tag_name: str) -> int:
    if tag_name == "h1":
        return 1
    if tag_name == "h2":
        return 2
    if tag_name == "h3":
        return 3
    if tag_name == "h4":
        return 4
    return 0


def is_stop_heading(text: str) -> bool:
    return normalize_text(text).lower() in STOP_HEADINGS


def extract_text(el: Tag) -> str:
    return normalize_text(el.get_text(" ", strip=True))


def is_good_paragraph(el: Tag) -> bool:
    text = extract_text(el)
    if len(text) < 15:
        return False
    
    # Evita paragrafi che sembrano didascalie o citazioni brevi
    if text.endswith(("...", ".", ":", ";")) and len(text.split()) < 15:
        return False
    
    return True


def parse_list(tag: Tag) -> list[str]:
    items = []
    for li in tag.find_all("li", recursive=False):
        li_text = clean_output(extract_text(li))
        if li_text and len(li_text) > 5 and len(li_text) < 200:
            items.append(f"- {li_text}")
    return items[:5]  # Massimo 5 elementi per lista


def parse_section_children(container: Tag, blocks: list[str]) -> bool:
    for node in container.find_all(["h2", "h3", "h4", "p", "ul", "ol"]):
        if not isinstance(node, Tag):
            continue

        # salta elementi dentro blocchi rumorosi
        skip_node = False
        for parent in node.parents:
            if parent == container:
                break
            parent_classes = parent.get("class", [])
            if any(c in parent_classes for c in ["navbox", "infobox", "gallery", "sidebar", "reflist"]):
                skip_node = True
                break
        if skip_node:
            continue

        if node.name in {"h2", "h3", "h4"}:
            heading = clean_output(extract_text(node))
            if not heading:
                continue

            if is_stop_heading(heading):
                return True

            blocks.append(f'{"#" * heading_level(node.name)} {heading}')
            continue

        if node.name == "p":
            if is_good_paragraph(node):
                text = clean_output(extract_text(node))
                if text:
                    blocks.append(text)
            continue

        if node.name in {"ul", "ol"}:
            list_items = parse_list(node)
            if list_items:
                blocks.extend(list_items)
            continue

    return False


class WikipediaParser(BaseParser):
    """
    Parser di en.wikipedia.org.

    Wikipedia e' il caso piu' semplice dei quattro: il contenuto sta tutto
    dentro '#mw-content-text' ed e' testo scritto da esseri umani, non dati
    tabellari. Il lavoro consiste quasi solo nel togliere l'apparato
    enciclopedico che circonda l'articolo — indice, note, riquadri laterali,
    box di avviso — e nel fermarsi dove finisce il testo vero, cioe' al primo
    titolo fra References, Notes, See also e simili (STOP_HEADINGS).
    """

    canonical_domain = "en.wikipedia.org"

    def fetch(self, url: str) -> str:
        """
        Scarica via HTTP semplice, senza browser headless.

        Le pagine di Wikipedia sono renderizzate lato server: l'HTML e' gia'
        completo nella prima risposta. Aprire Chromium darebbe lo stesso
        risultato in molti secondi in piu'.
        """
        return fetch_html(url)

    def domain_for(self, url: str) -> str:
        return self.canonical_domain

    def extract_title(self, soup) -> str:
        """Titolo senza il suffisso ' - Wikipedia' che il sito aggiunge al <title>."""
        title = extract_page_title(soup)
        return re.sub(r"\s*-\s*Wikipedia.*$", "", title).strip()

    def extract_blocks(self, soup, url: str, html: str) -> list[str]:
        content_root = soup.select_one("#mw-content-text") or soup.select_one(".mw-parser-output")
        if content_root is None:
            return []

        for selector in REMOVE_SELECTORS:
            for tag in content_root.select(selector):
                tag.decompose()

        parser_output = content_root.select_one(".mw-parser-output") or content_root

        blocks: list[str] = []
        parse_section_children(parser_output, blocks)
        return blocks

    def finalize(self, blocks: list[str]) -> str:
        """clean_output toglie gli artefatti del markup di MediaWiki (data-mw, mw-*)."""
        return clean_output("\n\n".join(blocks).strip())
