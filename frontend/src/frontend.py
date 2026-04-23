from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import requests

app = FastAPI()
templates = Jinja2Templates(directory="src/templates")

API_BASE_URL = "http://backend:8003"


def safe_get(url: str, params: dict | None = None):
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as e:
        return None, str(e)


def safe_post(url: str, payload: dict | None = None):
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as e:
        return None, str(e)


def load_domains_and_gs_urls():
    domains_data, domains_error = safe_get(f"{API_BASE_URL}/domains")

    domains = []
    gs_urls = []
    extra_errors = []

    if domains_error:
        extra_errors.append(f"Errore domains: {domains_error}")

    if domains_data and "domains" in domains_data:
        domains = domains_data["domains"]

        for domain in domains:
            gs_data, gs_error = safe_get(
                f"{API_BASE_URL}/fullgoldstandard",
                params={"domain": domain}
            )

            if gs_error:
                extra_errors.append(f"Errore GS per {domain}: {gs_error}")
                continue

            if gs_data and "goldstandard" in gs_data:
                for entry in gs_data["goldstandard"]:
                    url = entry.get("url")
                    if url:
                        gs_urls.append(url)

    return domains, gs_urls, extra_errors


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    domains, gs_urls, errors = load_domains_and_gs_urls()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "domains": domains,
            "gs_urls": gs_urls,
            "parse_result": None,
            "gold_result": None,
            "eval_result": None,
            "error": " | ".join(errors) if errors else None,
        },
    )


@app.post("/parse-ui", response_class=HTMLResponse)
def parse_ui(request: Request, url: str = Form(...)):
    domains, gs_urls, errors = load_domains_and_gs_urls()

    parse_result, parse_error = safe_get(f"{API_BASE_URL}/parse", params={"url": url})
    if parse_error:
        errors.append(f"Errore parse: {parse_error}")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "domains": domains,
            "gs_urls": gs_urls,
            "parse_result": parse_result,
            "gold_result": None,
            "eval_result": None,
            "error": " | ".join(errors) if errors else None,
        },
    )


@app.post("/evaluate-ui", response_class=HTMLResponse)
def evaluate_ui(request: Request, gs_url: str = Form(...)):
    domains, gs_urls, errors = load_domains_and_gs_urls()

    parse_result, parse_error = safe_get(f"{API_BASE_URL}/parse", params={"url": gs_url})
    gold_result, gold_error = safe_get(f"{API_BASE_URL}/goldstandard", params={"url": gs_url})

    if parse_error:
        errors.append(f"Errore parse: {parse_error}")
    if gold_error:
        errors.append(f"Errore goldstandard: {gold_error}")

    eval_result = None
    if parse_result and gold_result:
        eval_result, eval_error = safe_post(
            f"{API_BASE_URL}/evaluate",
            {
                "parsedtext": parse_result.get("parsedtext", ""),
                "goldtext": gold_result.get("goldtext", ""),
            },
        )
        if eval_error:
            errors.append(f"Errore evaluate: {eval_error}")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "domains": domains,
            "gs_urls": gs_urls,
            "parse_result": parse_result,
            "gold_result": gold_result,
            "eval_result": eval_result,
            "error": " | ".join(errors) if errors else None,
        },
    )