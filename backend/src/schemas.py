from fastapi import FastAPI
import json
import os
from src.parsers.wikipedia_parser import parse_wikipedia

app = FastAPI(title="Pipeline di Parsing Web")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOMAINS_FILE = os.path.join(BASE_DIR, "domains.json")

@app.get("/domains")
def get_domains():
    """Restituisce la lista dei domini supportati dal sistema."""
    try:
        with open(DOMAINS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"error": "File domains.json non trovato."}

@app.get("/parse")
def parse_url(url: str):
    """Endpoint GET /parse: analizza un URL e restituisce il testo estratto."""
    if "wikipedia.org" in url:
        return parse_wikipedia(url)
    else:
        return {"error": "Dominio non ancora supportato o URL non valido."}
