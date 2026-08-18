"""
Parser per il dominio it.tradingview.com.

Struttura del sito
------------------
TradingView e' una single page application React: i nomi delle classi CSS sono
generati a build time (es. 'title-QjjAoTcT') e cambiano ad ogni rilascio, quindi
sono inutilizzabili come selettori stabili. Il sito espone pero' un secondo
sistema di attributi, 'data-qa-id', usato dai loro test automatici: quelli sono
semantici e stabili nel tempo. Il parser si aggancia a quelli.

Ogni widget informativo della pagina ha un contenitore
'data-qa-id="<nome>-content"' preceduto in ordine di documento dal proprio <h2>.
Da qui le due scelte di fondo:

  * si tiene una whitelist esplicita dei widget informativi (KEEP_SECTIONS)
    invece di una blacklist: la pagina ne contiene una quindicina e la
    maggioranza e' rumore (grafici, gauge, idee degli utenti);
  * il titolo di sezione si ricava con find_previous('h2'), perche' l'heading
    sta fuori dal contenitore del contenuto ma sempre prima di esso.

Cosa viene escluso e perche'
----------------------------
  technicals, widget-analyst    gauge grafiche: il testo estraibile e' solo
                                "Neutro Vendi Compra" ripetuto, rumore puro
  financials-overview           etichette di assi di grafici
  idea-cards                    contenuto generato dagli utenti, non e'
                                informazione sul titolo
  widget-news                   elenco di titoli di notizie di terze parti,
                                equivalente a una sidebar
  seasonals, yielding_bonds,    widget numerici tabellari: un umano che
  etf-ownership, open-interest  costruisce il gold standard non li copia
  symbols-comparison            grafico di confronto
  symbol-faq-widget             domande frequenti generate dal sito da un
                                modello fisso ("Qual e' il prezzo di X
                                oggi?"): sono frasi ricostruite dai dati
                                gia' presenti nelle altre sezioni, non
                                informazione originale della pagina. Da
                                sole pesano circa tre quarti dei caratteri
                                estraibili e nessun essere umano le
                                copierebbe scrivendo a mano il testo di
                                riferimento: tenerle abbassava la
                                precision a 0.23.

Branch
------
  symbol   /symbols/<BORSA>-<TICKER>/       scheda completa dello strumento
  news     /symbols/<BORSA>-<TICKER>/news/  elenco notizie

ATTENZIONE sul branch 'news': l'elenco delle notizie e' costruito lato client
dopo il primo paint. L'HTML scaricato contiene solo gli scheletri di
caricamento ('news-card-skeleton-list-view'), non i titoli. Il parser lo
rileva e lo segnala invece di restituire silenziosamente una pagina vuota.
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

CANONICAL_DOMAIN = "it.tradingview.com"

# Widget informativi da tenere, per 'data-qa-id'. Whitelist: la pagina ne
# contiene molti altri e sono quasi tutti rumore (vedi docstring).
KEEP_SECTIONS: frozenset[str] = frozenset({
    "key-stats-id-content",             # Statistiche chiave / Punti chiave
    "upcoming-earnings-content",        # Prossimi utili
    "latest-earnings-summary-content",  # Ultimi utili
    "employees-section-content",        # Dipendenti
    "company-info-id-content",          # Dettagli + descrizione dell'azienda
    "classification-id-content",        # Classificazione (ETF)
    "etf-analysis-id-content",          # Profilo (ETF)
    "derivatives-section-content",      # Derivati (crypto)
})

# Contenitore che avvolge l'intera pagina: se lo si prendesse come sezione si
# reintrodurrebbe tutto il rumore che la whitelist serve a escludere.
WRAPPER_SECTION = "symbol-overview-page-section-content"

# Tag rimossi prima di qualunque estrazione.
NOISE_TAGS = ["script", "style", "noscript", "svg", "iframe", "canvas", "form"]

# Prefissi di classe (la parte prima del suffisso hashato) usati dai widget.
KV_BLOCK_PREFIX = "block-"

# Tag che non interrompono un paragrafo: se un blocco contiene solo questi,
# il suo testo va tenuto insieme e non spezzato riga per riga.
INLINE_TAGS = frozenset({"a", "span", "b", "i", "em", "strong", "br", "sup", "sub", "u", "small"})

# Caratteri invisibili che TradingView inserisce attorno ai numeri
# (marcatori di direzionalita' del testo) e nei titoli (BOM).
INVISIBLE_RE = re.compile(r"[​‎‏‪-‮﻿]")

# Righe di sola interfaccia che sopravvivono alla whitelist.
NOISE_LINE_RE = re.compile(
    r"^(grafico intero|visualizza sui grafici|vedi tutt\w*|mostra (di )?(piu'|più|tutt\w*)|"
    r"leggi (di )?(piu'|più)|altro nel.*|espandi|comprimi|"
    r"accedi|registrati|cerca|menu|—|–|-)$",
    re.IGNORECASE,
)

MIN_PARAGRAPH_CHARS = 60
MIN_LINE_CHARS = 2


def _clean(text: str) -> str:
    """Normalizza spazi e rimuove i caratteri invisibili del sito."""
    text = INVISIBLE_RE.sub("", text or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _keep_line(text: str) -> bool:
    """Scarta righe vuote, troppo corte o di sola interfaccia."""
    if len(text) < MIN_LINE_CHARS:
        return False
    return not NOISE_LINE_RE.match(text)


def _has_class_prefix(tag: Tag, prefix: str) -> bool:
    """
    Vero se il tag ha una classe che inizia con 'prefix'.

    Si confronta il prefisso e non la classe intera perche' TradingView
    appende un hash di build a ogni nome ('block-F7ijigkB'): il prefisso e'
    semantico e sopravvive ai rilasci, il suffisso no.
    """
    classes = tag.get("class")
    if not classes:
        return False
    return any(str(name).startswith(prefix) for name in classes)


def _extract_domain(url: str) -> str:
    """Host dell'URL; ripiega sul dominio canonico se l'URL non e' parsabile."""
    return (urlparse(url).hostname or CANONICAL_DOMAIN).lower()


def _extract_title(soup) -> str:
    """
    Titolo della pagina.

    Si preferisce l'<h1>, che contiene il nome pulito dello strumento
    ('Apple Inc'), al <title>, che e' ottimizzato per la SEO
    ('Grafico azione Apple - Prezzo azione NASDAQ:AAPL - TradingView').
    """
    h1 = soup.find("h1")
    if h1:
        title = _clean(h1.get_text(" ", strip=True))
        if title:
            return title
    return _clean(extract_page_title(soup))


def _branch(url: str) -> str:
    """Tipo di pagina, dedotto dal path."""
    path = urlparse(url).path.rstrip("/")
    if path.endswith("/news"):
        return "news"
    if "/symbols/" in path:
        return "symbol"
    return "generic"


def _section_heading(node: Tag) -> str:
    """
    Titolo della sezione a cui appartiene il contenitore.

    L'<h2> non e' dentro il contenitore del contenuto ma nell'header del widget,
    che lo precede sempre in ordine di documento: find_previous risale al piu'
    vicino, che e' quello giusto.
    """
    heading = node.find_previous("h2")
    return _clean(heading.get_text(" ", strip=True)) if heading else ""


def _is_kv_block(tag: Tag) -> bool:
    """Riconosce una cella etichetta/valore delle griglie di statistiche."""
    return _has_class_prefix(tag, KV_BLOCK_PREFIX)


def _render_kv_block(block: Tag) -> str:
    """
    Rende una cella come voce di elenco 'Etichetta valore'.

    La cella ha il nome della metrica nel primo figlio e il valore (piu'
    eventualmente la valuta) nei successivi. Se la struttura non e' quella
    attesa si ripiega sul testo completo, senza perdere l'informazione.

    Etichetta e valore non vengono separati da due punti: nella pagina
    sono due celle distinte di una griglia e quel carattere non compare
    da nessuna parte. Aggiungerlo sembra innocuo, ma la metrica lavora
    su token separati da spazio e produrrebbe 'emittente:' dove il testo
    di riferimento ha 'emittente': su una scheda con venticinque
    etichette sono cinquanta token che non combaciano.
    """
    children = block.find_all(recursive=False)
    if len(children) >= 2:
        label = _clean(children[0].get_text(" ", strip=True))
        value = _clean(" ".join(child.get_text(" ", strip=True) for child in children[1:]))
        if label and value:
            return f"- {label} {value}"

    text = _clean(block.get_text(" ", strip=True))
    return f"- {text}" if text else ""


def _is_paragraph_like(tag: Tag) -> bool:
    """
    Vero se il blocco va tenuto intero come paragrafo.

    Serve per la descrizione dell'azienda, che e' un div senza classe con
    dentro qualche link: scendendo ricorsivamente la si spezzerebbe in
    frammenti privi di senso.
    """
    if tag.name == "p":
        return True
    children = tag.find_all(recursive=False)
    if not children:
        return False
    if any(child.name not in INLINE_TAGS for child in children):
        return False
    return len(_clean(tag.get_text(" ", strip=True))) >= MIN_PARAGRAPH_CHARS


def _walk(node: Tag, lines: list[str]) -> None:
    """
    Percorre il sottoalbero raccogliendo celle, paragrafi e righe di testo.

    Stessa logica di parse_section_children() del parser Wikipedia: si scende
    finche' non si incontra un blocco riconoscibile, poi si emette.
    """
    for child in node.find_all(recursive=False):
        if not isinstance(child, Tag):
            continue

        if _is_kv_block(child):
            rendered = _render_kv_block(child)
            if rendered:
                lines.append(rendered)
            continue

        if _is_paragraph_like(child):
            text = _clean(child.get_text(" ", strip=True))
            if _keep_line(text):
                lines.append(text)
            continue

        if child.find(recursive=False):
            _walk(child, lines)
            continue

        text = _clean(child.get_text(" ", strip=True))
        if _keep_line(text):
            lines.append(text)


def _render_section(section: Tag) -> list[str]:
    """Rende un widget informativo, con il suo titolo di sezione."""
    blocks: list[str] = []

    heading = _section_heading(section)
    if heading:
        blocks.append(f"## {heading}")

    _walk(section, blocks)

    # Solo il titolo e nessun contenuto: il widget era vuoto, non lo emetto.
    if len(blocks) <= 1:
        return []
    return blocks


def _finalize(blocks: list[str]) -> str:
    """
    Compone il Markdown finale.

    Due accorgimenti: si eliminano le ripetizioni consecutive (i widget
    ripetono spesso lo stesso valore in versione compatta ed estesa) e le
    voci di elenco contigue si uniscono con un solo a capo, cosi' che una
    griglia di statistiche resti un elenco unico e non una sequenza di
    paragrafi separati.
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


def _looks_skeleton(soup) -> bool:
    """
    Vero se la pagina contiene solo scheletri di caricamento.

    Succede sulle pagine /news/, il cui elenco viene costruito in JavaScript
    dopo il primo paint: l'HTML salvato non contiene nessuna notizia.
    """
    return bool(soup.find_all(attrs={"data-qa-id": "news-card-skeleton-list-view"}))


def parse_tradingview(url: str, html_text: Optional[str] = None) -> dict:
    """
    Estrae il contenuto informativo di una pagina it.tradingview.com.

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
    branch = _branch(url)

    blocks: list[str] = []
    if title:
        blocks.append(f"# {title}")

    if branch == "news" and _looks_skeleton(soup):
        # Non restituisco una pagina quasi vuota fingendo che sia un risultato:
        # meglio dichiarare che questo tipo di pagina non e' parsabile da HTML
        # statico, cosi' il problema si vede in fase di evaluation.
        blocks.append(
            "L'elenco delle notizie di questa pagina viene costruito in JavaScript "
            "dopo il caricamento: l'HTML statico contiene solo segnaposto."
        )
        return build_result(url, domain, title, html, _finalize(blocks))

    for section in soup.find_all(attrs={"data-qa-id": True}):
        section_id = section.get("data-qa-id")
        if section_id == WRAPPER_SECTION or section_id not in KEEP_SECTIONS:
            continue
        blocks.extend(_render_section(section))

    return build_result(url, domain, title, html, _finalize(blocks))
