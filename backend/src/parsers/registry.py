"""
Registro dei parser: associa ogni dominio supportato al suo parser.

E' l'unico punto di dispatch del sistema. Aggiungere un dominio significa
scrivere una sottoclasse di BaseParser e aggiungere una riga qui: niente
'if domain == ...' sparsi in server.py, che e' il modo tipico in cui questo
genere di progetti smette di essere estendibile.

Le chiavi sono scritte senza 'www.': get_domain lo rimuove prima del
confronto, cosi' 'basketball-reference.com' e 'www.basketball-reference.com'
finiscono sullo stesso parser.
"""

from urllib.parse import urlparse

from src.parsers.basketball_reference_parser import BasketballReferenceParser
from src.parsers.morningstar_parser import MorningstarParser
from src.parsers.tradingview_parser import TradingViewParser
from src.parsers.wikipedia_parser import WikipediaParser

# I parser sono senza stato: una sola istanza per dominio basta e avanza.
PARSERS = {
    "en.wikipedia.org": WikipediaParser(),
    "basketball-reference.com": BasketballReferenceParser(),
    "global.morningstar.com": MorningstarParser(),
    "it.tradingview.com": TradingViewParser(),
}


def get_domain(url: str) -> str:
    """Host dell'URL, in minuscolo e senza 'www.'."""
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def get_parser(url: str):
    """
    Parser adatto all'URL e dominio riconosciuto.

    Returns:
        (parser, dominio) se il dominio e' supportato, altrimenti
        (None, dominio) — spetta al chiamante decidere cosa farne.
    """
    domain = get_domain(url)
    for key, parser in PARSERS.items():
        if domain == key or domain.endswith("." + key):
            return parser, domain
    return None, domain
