import json
import os


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
GSDATA_DIR = os.path.join(BASE_DIR, "gsdata")

DOMAIN_TO_FILE = {
    "wikipedia.org": "wikipedia_gs.json",
    "global.morningstar.com": "morningstar_gs.json",
    "www.basketball-reference.com": "basketballreference_gs.json",
    "it.tradingview.com": "tradingview_gs.json",
}


def get_gs_file_path(domain: str) -> str:
    if domain not in DOMAIN_TO_FILE:
        raise ValueError(f"Dominio non supportato: {domain}")
    return os.path.join(GSDATA_DIR, DOMAIN_TO_FILE[domain])


def load_goldstandard_by_domain(domain: str) -> list:
    file_path = get_gs_file_path(domain)

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File GS non trovato per il dominio: {domain}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ["goldstandard", "data", "entries", "items"]:
            value = data.get(key)
            if isinstance(value, list):
                return value

    raise ValueError(f"Il file GS per {domain} non contiene una lista valida.")


def get_goldstandard_entry_by_url(url: str) -> dict | None:
    for domain in DOMAIN_TO_FILE:
        try:
            entries = load_goldstandard_by_domain(domain)
            for entry in entries:
                if entry.get("url") == url:
                    return entry
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            continue

    return None