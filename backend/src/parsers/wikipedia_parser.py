import re
import requests
from bs4 import BeautifulSoup, Tag


STOP_HEADINGS = {
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
        if "usa l'anteprima" in low or "usa l'anteprima" in low:
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
    text = normalize_text(el.get_text(" ", strip=True))
    # Limita la lunghezza massima del paragrafo
    if len(text) > 500:
        text = text[:500] + "..."
    return text


def is_good_paragraph(el: Tag) -> bool:
    text = extract_text(el)
    if len(text) < 30:
        return False
    
    # Evita paragrafi che sembrano didascalie o citazioni brevi
    if text.endswith(("...", ".", ":", ";")) and len(text.split()) < 15:
        return False
    
    return True


def parse_list(tag: Tag) -> list[str]:
    items = []
    for li in tag.find_all("li", recursive=False):
        li_text = extract_text(li)
        if li_text and len(li_text) > 5 and len(li_text) < 200:
            items.append(f"- {li_text}")
    return items[:5]  # Massimo 5 elementi per lista


def parse_section_children(container: Tag, blocks: list[str]) -> bool:
    for node in container.children:
        if not isinstance(node, Tag):
            continue

        # Skip blocchi rumorosi
        classes = node.get("class", [])
        if any(c in classes for c in ["navbox", "infobox", "gallery", "sidebar"]):
            continue

        if node.name in {"h2", "h3", "h4"}:
            heading = extract_text(node)
            if not heading:
                continue

            if is_stop_heading(heading):
                return True

            blocks.append(f'{"#" * heading_level(node.name)} {heading}')
            continue

        if node.name == "p":
            if is_good_paragraph(node):
                blocks.append(extract_text(node))
            continue

        if node.name in {"ul", "ol"}:
            list_items = parse_list(node)
            if list_items:
                blocks.extend(list_items)
            continue

        if node.name == "section":
            should_stop = parse_section_children(node, blocks)
            if should_stop:
                return True

        # Skip altri elementi
        if node.name in {"div", "span"}:
            classes = node.get("class", [])
            if "thumb" in classes or "gallery" in classes:
                continue

    return False


def parse_wikipedia(url: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; WikipediaParser/1.0)"
    }

    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.title:
        title = soup.title.get_text(strip=True)
        title = re.sub(r"\s*-\s*Wikipedia.*$", "", title).strip()

    content_root = soup.select_one("#mw-content-text")
    if content_root is None:
        content_root = soup.select_one(".mw-parser-output")

    if content_root is None:
        return {
            "url": url,
            "domain": "wikipedia.org",
            "title": title,
            "htmltext": html,
            "parsedtext": "",
        }

    for selector in REMOVE_SELECTORS:
        for tag in content_root.select(selector):
            tag.decompose()

    parser_output = content_root.select_one(".mw-parser-output") or content_root

    blocks = []
    parse_section_children(parser_output, blocks)
    parsedtext = clean_output("\n\n".join(blocks))

    return {
        "url": url,
        "domain": "wikipedia.org",
        "title": title,
        "htmltext": html,
        "parsedtext": parsedtext,
    }