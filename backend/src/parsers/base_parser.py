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
        delay_before_return_html=1.5,   # lascia al JS del sito il tempo di
        scan_full_page=True,            # scommentare le tabelle e caricare il lazy content
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