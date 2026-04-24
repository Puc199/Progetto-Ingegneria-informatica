from urllib.parse import urlparse
from src.parsers.wikipedia_parser import parse_wikipedia
from src.parsers.basketball_reference_parser import parse_basketball_reference

PARSERS = {
    "wikipedia.org": parse_wikipedia,
    "basketball-reference.com": parse_basketball_reference,
    # "global.morningstar.com": parse_morningstar,
    # "it.tradingview.com": parse_tradingview,
}

def get_domain(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname

def get_parser(url: str):
    domain = get_domain(url)
    for key, parser in PARSERS.items():
        if domain == key or domain.endswith("." + key):
            return parser, domain
    return None, domain