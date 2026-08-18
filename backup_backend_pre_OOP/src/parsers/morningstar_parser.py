"""
Parser per il dominio global.morningstar.com.

Struttura del sito
------------------
Morningstar e' un'applicazione Vue con rendering lato server. A differenza di
TradingView non usa classi generate a build time ma un design system con nomi
BEM stabili e parlanti ('mdc-story-body__paragraph__mdc', 'mdc-heading__mdc'):
sono selettori affidabili e il parser si aggancia direttamente a quelli.

Branch
------
  article  /en-gb/<sezione>/<slug>
           Articolo editoriale. Il corpo e' dentro
           <article class="story__article__mdc">, suddiviso in blocchi
           'mdc-story-body__block__mdc' che possono essere titoli, paragrafi,
           elenchi o riquadri pubblicitari.

  quote    /en-<paese>/investments/stocks/<id>/quote
           Scheda titolo. Vedi la nota sotto.

Nota sul branch 'quote'
-----------------------
Le schede titolo sono gusci vuoti: l'HTML servito dal server contiene solo
navigazione, intestazione e footer (circa mille caratteri in tutto), mentre
prezzi, rating, metriche e profilo aziendale vengono caricati via XHR dopo
l'idratazione della pagina. Salvare la pagina dal browser con "solo HTML"
conserva l'HTML originale della rete, non il DOM idratato, quindi il
contenuto non c'e'.

Il parser riconosce la situazione e la dichiara, invece di restituire il
menu di navigazione spacciandolo per contenuto informativo: un parser che
sembra funzionare ma estrae boilerplate e' peggio di uno che dice di non
poter lavorare.

Scelte di estrazione
--------------------
  * l'ambito e' il solo corpo dell'articolo: le sezioni di coda
    ("More In Markets", "About the Author", "Securities Mentioned") stanno
    fuori da 'mdc-story-body__mdc' e vengono escluse senza bisogno di regole;
  * i riquadri <aside> sono esclusi: sono pubblicita' o rimandi ad altri
    articoli, mai contenuto della pagina corrente;
  * firma e data non vengono estratte: nel markup stanno fuori dal contenitore
    dell'articolo, mescolate a quelle dei feed di articoli correlati, e non
    sono attribuibili con certezza. La consegna chiede "titolo e corpo
    dell'articolo", quindi restano fuori.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import Tag

from src.parsers.base_parser import (
    build_result,
    extract_page_title,
    fetch_html_crawl4ai,
    make_soup,
)

CANONICAL_DOMAIN = "global.morningstar.com"

# Contenitore dell'articolo e del suo corpo.
ARTICLE_SELECTOR = "article.story__article__mdc"
STORY_BODY_SELECTOR = ".mdc-story-body__mdc"
STORY_BLOCK_CLASS = "mdc-story-body__block__mdc"

# I riquadri pubblicitari condividono la classe dei blocchi: si distinguono
# da questo prefisso.
AD_CLASS_PREFIX = "mdc-story-body__ad"

NOISE_TAGS = ["script", "style", "noscript", "svg", "iframe", "canvas", "form"]

# Tag di blocco da cui estrarre testo, e come renderli.
HEADING_LEVELS = {"h2": "##", "h3": "###", "h4": "####"}
LIST_TAGS = frozenset({"ul", "ol"})
TEXT_TAGS = frozenset({"p", "blockquote"})

# Blocchi da saltare sempre: pubblicita', rimandi, immagini, incorporati.
SKIP_TAGS = frozenset({"aside", "figure", "picture", "img", "video"})

# Sotto questa soglia di testo nel body la pagina non e' stata idratata.
SHELL_MAX_CHARS = 3_000

MIN_LINE_CHARS = 3

# Coda che Morningstar aggiunge al <title> di ogni pagina.
TITLE_SUFFIX_RE = re.compile(r"\s*\|\s*Morningstar\b.*$", re.IGNORECASE)

# Righe di sola interfaccia che possono sopravvivere all'estrazione.
NOISE_LINE_RE = re.compile(
    r"^(sponsored|advertisement|pubblicit[aà]|read more|leggi di piu'|leggi di più|"
    r"sign up|subscribe|share this|learn more|—|–|-)$",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    """Normalizza spazi e caratteri non separabili."""
    text = (text or "").replace("\xa0", " ").replace("​", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _keep_line(text: str) -> bool:
    """Scarta righe vuote, troppo corte o di sola interfaccia."""
    if len(text) < MIN_LINE_CHARS:
        return False
    return not NOISE_LINE_RE.match(text)


def _extract_domain(url: str) -> str:
    """Host dell'URL; ripiega sul dominio canonico se l'URL non e' parsabile."""
    return (urlparse(url).hostname or CANONICAL_DOMAIN).lower()


def _extract_title(soup) -> str:
    """
    Titolo della pagina.

    L'<h1> contiene il titolo reale; il <title> ha in coda il nome
    dell'edizione ("... | Morningstar UK"), che va tolto.
    """
    h1 = soup.find("h1")
    if h1:
        title = _clean(h1.get_text(" ", strip=True))
        if title:
            return title

    return _clean(TITLE_SUFFIX_RE.sub("", extract_page_title(soup)))


def _branch(url: str, soup) -> str:
    """
    Tipo di pagina.

    Si guarda prima il markup e poi l'URL: il markup e' la prova che
    l'articolo c'e' davvero, il path e' solo un indizio.
    """
    if soup.select_one(ARTICLE_SELECTOR):
        return "article"
    if "/investments/" in urlparse(url).path or url.rstrip("/").endswith("/quote"):
        return "quote"
    return "generic"


def _is_ad(block: Tag) -> bool:
    """Vero se il blocco e' un riquadro pubblicitario o un rimando."""
    classes = block.get("class") or []
    return any(str(name).startswith(AD_CLASS_PREFIX) for name in classes)


def _render_list(block: Tag) -> list[str]:
    """Rende un elenco puntato o numerato come voci Markdown."""
    lines: list[str] = []
    for item in block.find_all("li"):
        text = _clean(item.get_text(" ", strip=True))
        if _keep_line(text):
            lines.append(f"- {text}")
    return lines


def _render_block(block: Tag) -> list[str]:
    """Rende un singolo blocco del corpo dell'articolo."""
    if block.name in SKIP_TAGS or _is_ad(block):
        return []

    if block.name in HEADING_LEVELS:
        text = _clean(block.get_text(" ", strip=True))
        return [f"{HEADING_LEVELS[block.name]} {text}"] if _keep_line(text) else []

    if block.name in LIST_TAGS:
        return _render_list(block)

    if block.name in TEXT_TAGS:
        text = _clean(block.get_text(" ", strip=True))
        return [text] if _keep_line(text) else []

    # Contenitore generico: si tiene solo se contiene testo proprio e non
    # altri blocchi, per non duplicare quello che verra' emesso dopo.
    if block.find(class_=STORY_BLOCK_CLASS):
        return []
    text = _clean(block.get_text(" ", strip=True))
    return [text] if _keep_line(text) else []


def _collect_article(soup) -> list[str]:
    """
    Raccoglie i blocchi del corpo dell'articolo, in ordine di documento.

    L'ambito e' 'mdc-story-body__mdc': tutto cio' che sta fuori (rimandi ad
    altri articoli, biografia dell'autore, titoli citati) resta escluso.
    """
    body = soup.select_one(STORY_BODY_SELECTOR)
    if body is None:
        return []

    blocks: list[str] = []
    for block in body.find_all(class_=STORY_BLOCK_CLASS):
        blocks.extend(_render_block(block))

    return blocks


def _fallback_article(soup) -> list[str]:
    """
    Estrazione di riserva quando i blocchi non sono riconoscibili.

    Puo' servire se Morningstar cambia i nomi delle classi del design system:
    meglio degradare su titoli e paragrafi dentro <article> che restituire
    una pagina vuota.
    """
    article = soup.select_one(ARTICLE_SELECTOR) or soup.find("article")
    if article is None:
        return []

    blocks: list[str] = []
    for node in article.find_all(["h2", "h3", "h4", "p", "ul", "ol"]):
        if node.find_parent(SKIP_TAGS):
            continue
        blocks.extend(_render_block(node))

    return blocks


def _body_text_length(soup) -> int:
    """Quantita' di testo presente nella pagina, per riconoscere i gusci vuoti."""
    body = soup.find("body")
    return len(_clean(body.get_text(" ", strip=True))) if body else 0


def _finalize(blocks: list[str]) -> str:
    """
    Compone il Markdown finale.

    Come per gli altri parser: via le ripetizioni consecutive e voci di
    elenco contigue unite in un blocco solo.
    """
    cleaned: list[str] = []
    previous: Optional[str] = None

    for block in blocks:
        block = block.strip()
        if not block or block == previous:
            continue
        cleaned.append(block)
        previous = block

    output: list[str] = []
    bullets: list[str] = []

    for block in cleaned:
        if block.startswith("- "):
            bullets.append(block)
            continue
        if bullets:
            output.append("\n".join(bullets))
            bullets = []
        output.append(block)

    if bullets:
        output.append("\n".join(bullets))

    text = "\n\n".join(output)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_morningstar(url: str, html_text: Optional[str] = None) -> dict:
    """
    Estrae il contenuto informativo di una pagina global.morningstar.com.

    Args:
        url: URL della pagina, usato anche per riconoscere il tipo di pagina.
        html_text: HTML gia' disponibile. Se assente la pagina viene scaricata.
                   Passarlo e' la modalita' usata in fase di evaluation, dove
                   si lavora sempre sull'HTML statico salvato nel database.

    Returns:
        Dizionario con url, domain, title, html_text, parsed_text (Markdown).
    """
    html = html_text if html_text else fetch_html_crawl4ai(url)
    domain = _extract_domain(url)

    if not html:
        return build_result(url, domain, "", "", "")

    soup = make_soup(html)
    for tag in soup(NOISE_TAGS):
        tag.decompose()

    title = _extract_title(soup)
    branch = _branch(url, soup)

    blocks: list[str] = []
    if title:
        blocks.append(f"# {title}")

    if branch == "article":
        body = _collect_article(soup)
        if not body:
            body = _fallback_article(soup)
        blocks.extend(body)
        return build_result(url, domain, title, html, _finalize(blocks))

    # Guscio non idratato: lo dichiaro invece di restituire il menu di
    # navigazione facendolo passare per contenuto.
    if _body_text_length(soup) < SHELL_MAX_CHARS:
        blocks.append(
            "Il contenuto di questa pagina (prezzi, rating, metriche e profilo aziendale) "
            "viene caricato via XHR dopo l'idratazione: l'HTML statico contiene solo "
            "navigazione e footer."
        )
        return build_result(url, domain, title, html, _finalize(blocks))

    blocks.extend(_fallback_article(soup))
    return build_result(url, domain, title, html, _finalize(blocks))
