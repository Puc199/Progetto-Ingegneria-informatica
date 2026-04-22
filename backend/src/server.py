from fastapi import FastAPI, HTTPException
from src.parsers.registry import get_parser
from src.schemas import ParseResponse, ParsePostRequest
import json, os

app = FastAPI(title="Pipeline di Parsing Web")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOMAINS_FILE = os.path.join(BASE_DIR, "domains.json")

@app.get("/domains")
def get_domains():
    try:
        with open(DOMAINS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="File domains.json non trovato.")

@app.get("/parse")
def parse_get(url: str):
    parser, domain = get_parser(url)
    if parser is None:
        raise HTTPException(status_code=400, detail=f"Dominio non supportato: {domain}")
    result = parser(url)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return result

@app.post("/parse")
def parse_post(body: ParsePostRequest):
    parser, domain = get_parser(body.url)
    if parser is None:
        raise HTTPException(status_code=400, detail=f"Dominio non supportato: {domain}")
    # passa l'html già scaricato se il parser lo supporta
    result = parser(body.url, htmltext=body.htmltext)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return result