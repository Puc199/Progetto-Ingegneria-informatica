from fastapi import FastAPI, HTTPException
from src.parsers.registry import get_parser
from src.schemas import ParsePostRequest, EvaluateRequest
from src.services.evaluator import token_level_eval
import json
import os

app = FastAPI(title="Pipeline di Parsing Web")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOMAINS_FILE = os.path.join(BASE_DIR, "domains.json")
GSDATA_DIR = os.path.join(BASE_DIR, "gsdata")


def load_domains() -> list[str]:
    try:
        with open(DOMAINS_FILE, "r", encoding="utf-8") as f:
            domains = json.load(f)
        if not isinstance(domains, list):
            raise HTTPException(status_code=500, detail="domains.json deve contenere una lista.")
        return domains
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="File domains.json non trovato.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="domains.json non è un JSON valido.")


def normalize_parse_result(result: dict) -> dict:
    return {
        "url": result.get("url"),
        "domain": result.get("domain"),
        "title": result.get("title"),
        "html_text": result.get("html_text"),
        "parsed_text": result.get("parsed_text"),
    }


def normalize_gs_entry(entry: dict) -> dict:
    return {
        "url": entry.get("url"),
        "domain": entry.get("domain"),
        "title": entry.get("title"),
        "html_text": entry.get("html_text"),
        "gold_text": entry.get("gold_text"),
    }


def domain_to_gs_filename(domain: str) -> str:
    base = domain.lower()
    if base.startswith("www."):
        base = base[4:]
    for suffix in [".com", ".org", ".it", ".net", ".edu"]:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    base = base.replace(".", "")
    base = base.replace("-", "")
    base = base.replace("_", "")
    return f"{base}_gs.json"


def get_gs_file_path(domain: str) -> str:
    candidate = os.path.join(GSDATA_DIR, domain_to_gs_filename(domain))
    if os.path.exists(candidate):
        return candidate

    if not os.path.isdir(GSDATA_DIR):
        return candidate

    for filename in os.listdir(GSDATA_DIR):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(GSDATA_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                first_domain = data[0].get("domain")
                if first_domain == domain:
                    return path
        except Exception:
            continue

    return candidate


def load_gold_standard_for_domain(domain: str) -> list[dict]:
    supported_domains = load_domains()
    if domain not in supported_domains:
        raise HTTPException(status_code=400, detail=f"Dominio non supportato: {domain}")

    gs_file = get_gs_file_path(domain)

    try:
        with open(gs_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"File GS non trovato per il dominio: {domain}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Il GS del dominio {domain} non è un JSON valido.")

    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail=f"Il GS del dominio {domain} deve essere una lista di entry.")

    return data


@app.get("/domains")
def get_domains():
    return {"domains": load_domains()}


@app.get("/parse")
def parse_get(url: str):
    parser, domain = get_parser(url)

    if parser is None:
        raise HTTPException(status_code=400, detail=f"Dominio non supportato: {domain}")

    try:
        result = parser(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore durante il parsing: {str(e)}")

    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Il parser non ha restituito un dizionario valido.")

    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    return normalize_parse_result(result)


@app.post("/parse")
def parse_post(body: ParsePostRequest):
    url = str(body.url)
    parser, domain = get_parser(url)

    if parser is None:
        raise HTTPException(status_code=400, detail=f"Dominio non supportato: {domain}")

    try:
        result = parser(url, html_text=body.html_text)
    except TypeError:
        try:
            result = parser(url, htmltext=body.html_text)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Errore durante il parsing: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore durante il parsing: {str(e)}")

    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Il parser non ha restituito un dizionario valido.")

    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    return normalize_parse_result(result)


@app.get("/gold_standard")
def get_gold_standard(url: str):
    parser, domain = get_parser(url)

    if parser is None:
        raise HTTPException(status_code=400, detail=f"Dominio non supportato: {domain}")

    entries = load_gold_standard_for_domain(domain)

    for entry in entries:
        if entry.get("url") == url:
            return normalize_gs_entry(entry)

    raise HTTPException(status_code=404, detail="URL non presente nel Gold Standard.")


@app.get("/full_gold_standard")
def get_full_gold_standard(domain: str):
    entries = load_gold_standard_for_domain(domain)
    return {"gold_standard": [normalize_gs_entry(entry) for entry in entries]}


@app.post("/evaluate")
def evaluate(body: EvaluateRequest):
    scores = token_level_eval(body.parsed_text, body.gold_text)
    return {
        "token_level_eval": {
            "precision": scores["precision"],
            "recall": scores["recall"],
            "f1": scores["f1"]
        }
    }


@app.get("/full_gs_eval")
def full_gs_eval(domain: str):
    entries = load_gold_standard_for_domain(domain)

    if not entries:
        raise HTTPException(status_code=404, detail=f"Nessuna entry GS trovata per il dominio: {domain}")

    precisions = []
    recalls = []
    f1s = []

    for entry in entries:
        url = entry.get("url")
        if not url:
            continue

        parser, _ = get_parser(url)
        if parser is None:
            continue

        html_text = entry.get("html_text")
        gold_text = entry.get("gold_text")

        try:
            if html_text is not None:
                parsed = parser(url, html_text=html_text)
            else:
                parsed = parser(url)
        except TypeError:
            try:
                if html_text is not None:
                    parsed = parser(url, htmltext=html_text)
                else:
                    parsed = parser(url)
            except Exception:
                continue
        except Exception:
            continue

        if not isinstance(parsed, dict):
            continue

        if "error" in parsed:
            continue

        parsed_text = parsed.get("parsed_text")
        if parsed_text is None:
            parsed_text = parsed.get("parsedtext", "")

        if gold_text is None:
            continue

        scores = token_level_eval(parsed_text, gold_text)
        precisions.append(scores["precision"])
        recalls.append(scores["recall"])
        f1s.append(scores["f1"])

    if not precisions:
        raise HTTPException(status_code=500, detail="Impossibile calcolare la valutazione aggregata del GS.")

    return {
        "token_level_eval": {
            "precision": sum(precisions) / len(precisions),
            "recall": sum(recalls) / len(recalls),
            "f1": sum(f1s) / len(f1s)
        }
    }