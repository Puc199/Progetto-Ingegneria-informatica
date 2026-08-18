"""
Utility condivise fra i parser.

Modifiche rispetto alla versione precedente:
  * rimossi i print() di debug da build_result (rumore nei log e rallentamento
    su HTML da centinaia di KB);
  * CrawlerRunConfig configurabile per dominio, come richiesto dalla consegna
    ("agire sulla configurazione per migliorare l'output del parsing");
  * i kwargs non supportati dalla versione di crawl4ai installata vengono
    scartati automaticamente invece di far esplodere il crawler;
  * si restituisce result.html (HTML grezzo) e NON cleaned_html: cleaned_html
    rimuove i commenti, e su basketball-reference i commenti contengono le tabelle.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Configurazioni Crawl4AI per dominio (chiave = sottostringa dell'host)
RUN_CONFIGS: dict[str, dict] = {
    "basketball-reference.com": dict(
        cache_mode=CacheMode.BYPASS,
        wait_until="domcontentloaded",
        page_timeout=45000,
        # Niente scan_full_page: su questo sito le tabelle non sono caricate
        # pigramente, stanno gia' nell'HTML dentro commenti, ed e'
        # _uncomment_hidden_content() a reinserirle nel DOM dopo il download.
        # Far scorrere tutta la pagina costava decine di secondi per niente.
        delay_before_return_html=0.5,
        excluded_tags=["script", "style", "noscript", "svg", "form"],
        remove_overlay_elements=True,
        exclude_external_links=True,
        word_count_threshold=0,
    ),
    "wikipedia.org": dict(
        cache_mode=CacheMode.BYPASS,
        wait_until="domcontentloaded",
        page_timeout=30000,
        excluded_tags=["script", "style", "noscript"],
        word_count_threshold=0,
    ),
}
DEFAULT_RUN_CONFIG = dict(cache_mode=CacheMode.BYPASS, page_timeout=30000)


def _build_run_config(url: str) -> CrawlerRunConfig:
    """Costruisce la config scartando i kwargs non supportati dalla versione installata."""
    kwargs = DEFAULT_RUN_CONFIG
    for key, cfg in RUN_CONFIGS.items():
        if key in (url or "").lower():
            kwargs = cfg
            break
    try:
        return CrawlerRunConfig(**kwargs)
    except TypeError:
        supported = getattr(CrawlerRunConfig.__init__, "__code__", None)
        names = set(supported.co_varnames) if supported else set()
        safe = {k: v for k, v in kwargs.items() if k in names}
        return CrawlerRunConfig(**safe)


def fetch_html(url: str) -> str:
    """Fallback HTTP semplice (nessun JS)."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    # requests ripiega su ISO-8859-1 quando il server non dichiara il charset:
    # su Basketball-Reference questo sfascia la sezione Translations
    # (cirillico, greco, ebraico, CJK) trasformandola in mojibake.
    if "charset" not in response.headers.get("Content-Type", "").lower():
        response.encoding = response.apparent_encoding or "utf-8"

    return response.text


async def _crawl4ai_fetch(url: str) -> str:
    browser_cfg = BrowserConfig(browser_type="chromium", headless=True, verbose=False)
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=_build_run_config(url))

    if not result.success:
        raise RuntimeError(result.error_message or f"Errore Crawl4AI su {url}")

    # NB: result.html (grezzo), non cleaned_html: i commenti vanno preservati.
    return result.html or ""


def fetch_html_crawl4ai(url: str) -> str:
    try:
        html = asyncio.run(_crawl4ai_fetch(url))
        if html and html.strip():
            return html
    except Exception as exc:
        logger.warning("Crawl4AI fallito su %s (%s), passo al fetch HTTP", url, exc)
    return fetch_html(url)


async def _crawl4ai_parse_raw_html(html_text: str) -> str:
    browser_cfg = BrowserConfig(browser_type="chromium", headless=True, verbose=False)
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=f"raw:{html_text}",
                                    config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS))
    if not result.success:
        raise RuntimeError(result.error_message or "Errore Crawl4AI su HTML diretto")
    return result.html or html_text


def parse_raw_html_with_crawl4ai(html_text: str) -> str:
    return asyncio.run(_crawl4ai_parse_raw_html(html_text))


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def extract_page_title(soup: BeautifulSoup) -> str:
    return soup.title.get_text(strip=True) if soup.title else ""


def build_result(url: str, domain: str, title: str, html_text: str, parsed_text: str) -> dict:
    return {
        "url": url,
        "domain": domain,
        "title": title or "",
        "html_text": html_text or "",
        "parsed_text": parsed_text or "",
    }

# ---------------------------------------------------------------------------
# La classe base dei parser
# ---------------------------------------------------------------------------

class BaseParser(ABC):
    """
    Classe base astratta di tutti i parser di dominio.

    Perche' una classe e non quattro funzioni indipendenti. I quattro siti sono
    diversissimi fra loro, ma il ciclo di vita del parsing e' sempre lo stesso:

        1. si ottiene l'HTML (dal database in fase di valutazione, dalla rete
           altrimenti)
        2. lo si trasforma in un albero navigabile
        3. si prepara l'albero: ogni sito ha il suo rumore da togliere, e
           Basketball-Reference ha per di piu' del contenuto da riportare alla
           luce prima di poterlo leggere
        4. si estrae il titolo
        5. si estraggono i blocchi informativi, ed e' l'unico passo davvero
           specifico di ogni sito
        6. si compone il Markdown finale

    Questo metodo 'parse' e' un template method: fissa la sequenza una volta
    sola e lascia alle sottoclassi il compito di riempire i singoli passi. Il
    vantaggio pratico si vede quando si aggiunge un dominio: si scrive una
    sottoclasse, si implementa 'extract_blocks', e tutto il resto — il fetch
    con la configurazione Crawl4AI giusta, la gestione dell'HTML vuoto, il
    formato del dizionario di uscita — arriva gratis e identico agli altri.

    Il vantaggio meno ovvio e' che i quattro parser non possono piu' divergere
    di nascosto: se domani il formato del risultato cambia, cambia in un punto
    solo. Prima quel formato era ripetuto quattro volte, e infatti due parser
    dichiaravano il dominio in un modo e due in un altro.

    Le sottoclassi restano leggere perche' la logica di estrazione, che e'
    lunga e gia' verificata sul Gold Standard, sta nelle funzioni private di
    ciascun modulo: la classe descrive *cosa* succede e in che ordine, le
    funzioni *come*. Il refactoring a oggetti non ha quindi cambiato di una
    virgola i risultati delle metriche.
    """

    #: Dominio canonico gestito dalla sottoclasse (es. "en.wikipedia.org").
    canonical_domain: str = ""

    # -- ciclo di vita ------------------------------------------------------

    def parse(self, url: str, html_text: Optional[str] = None) -> dict:
        """
        Estrae il contenuto informativo di una pagina.

        Args:
            url: indirizzo della pagina, usato anche per riconoscere il tipo
                 di pagina all'interno del dominio.
            html_text: HTML gia' disponibile. Se assente la pagina viene
                       scaricata. Passarlo e' la modalita' usata in fase di
                       valutazione, dove si lavora sempre sull'HTML statico
                       salvato nel database.

        Returns:
            Dizionario con url, domain, title, html_text, parsed_text.
        """
        html = html_text if html_text and str(html_text).strip() else self.fetch(url)
        domain = self.domain_for(url)

        if not html:
            return build_result(url, domain, "", "", "")

        soup = make_soup(html)
        self.prepare(soup)

        title = self.extract_title(soup)

        blocks: list[str] = []
        if title:
            blocks.append(f"# {title}")
        blocks.extend(self.extract_blocks(soup, url, html))

        return build_result(url, domain, title, html, self.finalize(blocks))

    def __call__(self, url: str, html_text: Optional[str] = None) -> dict:
        """
        Permette di usare un'istanza dove prima c'era una funzione.

        Il registro dei parser espone oggetti, ma i chiamanti continuano a
        scrivere 'parser(url, html_text=...)': il passaggio a oggetti non ha
        richiesto di toccare server.py.
        """
        return self.parse(url, html_text)

    @property
    def name(self) -> str:
        """Nome del parser, salvato in parsed_documents.parser_name."""
        return type(self).__name__

    # -- passi con un comportamento predefinito -----------------------------

    def fetch(self, url: str) -> str:
        """
        Scarica la pagina. Crawl4AI, come chiede la consegna, con fallback HTTP.

        Wikipedia ridefinisce questo metodo: le sue pagine sono renderizzate
        lato server e aprire un browser headless costerebbe secondi per un
        risultato identico.
        """
        return fetch_html_crawl4ai(url)

    def domain_for(self, url: str) -> str:
        """Host dell'URL; ripiega sul dominio canonico se l'URL non e' parsabile."""
        return (urlparse(url).hostname or self.canonical_domain).lower()

    def prepare(self, soup: BeautifulSoup) -> None:
        """
        Prepara l'albero prima dell'estrazione. Di base non fa nulla.

        E' il punto in cui ogni sito toglie il proprio rumore, e in cui
        Basketball-Reference riporta nel DOM le tabelle che il sito nasconde
        dentro commenti HTML.
        """

    def extract_title(self, soup: BeautifulSoup) -> str:
        """Titolo della pagina, dal tag <title>."""
        return extract_page_title(soup)

    def finalize(self, blocks: list[str]) -> str:
        """Compone il Markdown finale a partire dai blocchi estratti."""
        return "\n\n".join(b for b in blocks if b and b.strip()).strip()

    # -- il passo che ogni dominio deve implementare ------------------------

    @abstractmethod
    def extract_blocks(self, soup: BeautifulSoup, url: str, html: str) -> list[str]:
        """
        Blocchi informativi della pagina, gia' in Markdown.

        Il titolo non va incluso: lo antepone 'parse'.
        """
