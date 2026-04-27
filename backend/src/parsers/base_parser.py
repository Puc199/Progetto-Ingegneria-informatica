import asyncio
import requests
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


async def _crawl4ai_fetch(url: str) -> str:
    browser_cfg = BrowserConfig(
        browser_type="chromium",
        headless=True,
        verbose=False
    )
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)

    if not result.success:
        raise Exception(result.error_message or f"Errore Crawl4AI su {url}")

    return result.html or result.cleaned_html or ""


def fetch_html_crawl4ai(url: str) -> str:
    try:
        html = asyncio.run(_crawl4ai_fetch(url))
        if html and html.strip():
            return html
    except Exception:
        pass

    return fetch_html(url)


async def _crawl4ai_parse_raw_html(html_text: str) -> str:
    browser_cfg = BrowserConfig(
        browser_type="chromium",
        headless=True,
        verbose=False
    )
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=f"raw:{html_text}", config=run_cfg)

    if not result.success:
        raise Exception(result.error_message or "Errore Crawl4AI su HTML diretto")

    return result.html or result.cleaned_html or html_text


def parse_raw_html_with_crawl4ai(html_text: str) -> str:
    return asyncio.run(_crawl4ai_parse_raw_html(html_text))


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def extract_page_title(soup: BeautifulSoup) -> str:
    if soup.title:
        return soup.title.get_text(strip=True)
    return ""


def build_result(url: str, domain: str, title: str, html_text: str, parsed_text: str) -> dict:
    return {
        "url": url,
        "domain": domain,
        "title": title,
        "html_text": html_text,
        "parsed_text": parsed_text,
    }