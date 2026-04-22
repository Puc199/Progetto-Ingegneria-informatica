from urllib.parse import urlparse
from src.parsers.wikipedia_parser import parse_wikipedia

PARSERS = {
    "wikipedia.org": parse_wikipedia,
    # "basketball-reference.com": parse_basketball_reference,
    # "global.morningstar.com": parse_morningstar,
    # "it.tradingview.com": parse_tradingview,
}

def get_domain(url: str) -> str:
    hostname = urlparse(url).netloc.lower()
    hostname = hostname.replace("www.", "")
    return hostname

def get_parser(url: str):
    domain = get_domain(url)
    for key in PARSERS:
        if key in domain:
            return PARSERS[key], domain
    return None, domain