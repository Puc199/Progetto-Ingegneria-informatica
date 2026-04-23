from fastapi import FastAPI, HTTPException
from src.parsers.registry import get_parser
from src.schemas import ParsePostRequest
import json
import os


app = FastAPI(title="Pipeline di Parsing Web")


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOMAINS_FILE = os.path.join(BASE_DIR, "domains.json")


@app.get("/domains")
def get_domains():
    try:
        with open(DOMAINS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="File domains.json non trovato.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="domains.json non è un JSON valido.")


@app.get("/parse")
def parse_get(url: str):
    parser, domain = get_parser(url)

    if parser is None:
        raise HTTPException(
            status_code=400,
            detail=f"Dominio non supportato: {domain}"
        )

    try:
        result = parser(url)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Errore durante il parsing: {str(e)}"
        )

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=500,
            detail="Il parser non ha restituito un dizionario valido."
        )

    if "error" in result:
        raise HTTPException(
            status_code=502,
            detail=result["error"]
        )

    return {
        "url": result.get("url"),
        "domain": result.get("domain"),
        "title": result.get("title"),
        "parsedtext": result.get("parsedtext"),
    }


@app.post("/parse")
def parse_post(body: ParsePostRequest):
    parser, domain = get_parser(body.url)

    if parser is None:
        raise HTTPException(
            status_code=400,
            detail=f"Dominio non supportato: {domain}"
        )

    try:
        result = parser(body.url)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Errore durante il parsing: {str(e)}"
        )

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=500,
            detail="Il parser non ha restituito un dizionario valido."
        )

    if "error" in result:
        raise HTTPException(
            status_code=502,
            detail=result["error"]
        )

    return {
        "url": result.get("url"),
        "domain": result.get("domain"),
        "title": result.get("title"),
        "parsedtext": result.get("parsedtext"),
    }