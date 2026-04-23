from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import requests

app = FastAPI()
templates = Jinja2Templates(directory="templates")

API_BASE_URL = "http://backend:8003"


def safe_get(url, params=None):
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as e:
        return None, str(e)


def safe_post(url, payload=None):
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as e:
        return None, str(e)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    domains, domains_error = safe_get(f"{API_BASE_URL}/domains")

    gs_urls = []
    if domains and "domains" in domains:
        for domain in domains["domains"]:
            gs_data, _ = safe_get(f"{API_BASE_URL}/fullgoldstandard", params={"domain": domain})
            if gs_data and "goldstandard" in gs_data:
                for entry in gs_data["goldstandard"]:
                    gs_urls.append(entry["url"])

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "domains": domains["domains"] if domains and "domains" in domains else [],
            "gs_urls": gs_urls,
            "parse_result": None,
            "gold_result": None,
            "eval_result": None,
            "error": domains_error
        }
    )


@app.post("/parse-ui", response_class=HTMLResponse)
def parse_ui(request: Request, url: str = Form(...)):
    domains, _ = safe_get(f"{API_BASE_URL}/domains")

    parse_result, error = safe_get(f"{API_BASE_URL}/parse", params={"url": url})

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "domains": domains["domains"] if domains and "domains" in domains else [],
            "gs_urls": [],
            "parse_result": parse_result,
            "gold_result": None,
            "eval_result": None,
            "error": error
        }
    )


@app.post("/evaluate-ui", response_class=HTMLResponse)
def evaluate_ui(request: Request, gs_url: str = Form(...)):
    domains, _ = safe_get(f"{API_BASE_URL}/domains")

    gs_urls = []
    if domains and "domains" in domains:
        for domain in domains["domains"]:
            gs_data, _ = safe_get(f"{API_BASE_URL}/fullgoldstandard", params={"domain": domain})
            if gs_data and "goldstandard" in gs_data:
                for entry in gs_data["goldstandard"]:
                    gs_urls.append(entry["url"])

    parse_result, parse_error = safe_get(f"{API_BASE_URL}/parse", params={"url": gs_url})
    gold_result, gold_error = safe_get(f"{API_BASE_URL}/goldstandard", params={"url": gs_url})

    eval_result = None
    error = parse_error or gold_error

    if parse_result and gold_result:
        eval_result, eval_error = safe_post(
            f"{API_BASE_URL}/evaluate",
            {
                "parsedtext": parse_result["parsedtext"],
                "goldtext": gold_result["goldtext"]
            }
        )
        if eval_error:
            error = eval_error

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "domains": domains["domains"] if domains and "domains" in domains else [],
            "gs_urls": gs_urls,
            "parse_result": parse_result,
            "gold_result": gold_result,
            "eval_result": eval_result,
            "error": error
        }
    )