"""
Web UI del progetto.

Un principio, senza eccezioni: questo servizio non conosce ne' il database ne'
i parser. Tutto passa dalle API REST del backend. Se una funzione serve alla
UI e l'API non ce l'ha, va aggiunta all'API, non aggirata da qui.

Quattro pagine, una responsabilita' ciascuna:

  /                home, stato del sistema e domini supportati
  /parser          prova un parser su un URL, in modalita' live o local
  /gold-standard   costruisce e gestisce il Gold Standard nel database
  /stats           statistiche aggregate per dominio
"""

from __future__ import annotations

import os
from typing import Any, Optional

import requests
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Web UI - Pipeline di Parsing Web")
templates = Jinja2Templates(directory="src/templates")

# Impostato dal docker-compose; il default serve all'esecuzione locale.
API_BASE_URL = os.getenv("API_BASE_URL", "http://backend:8003")

# Matricole del gruppo, mostrate in home come richiesto dalla consegna.
MATRICOLE = os.getenv("MATRICOLE", "matricola1, matricola2, matricola3")

# Il parsing live scarica la pagina con un browser headless: puo' richiedere
# parecchi secondi, molto piu' di una normale chiamata REST.
TIMEOUT_SHORT = 15
TIMEOUT_LONG = 240


def _error_message(response: requests.Response) -> str:
    """
    Messaggio d'errore leggibile a partire dalla risposta del backend.

    Il backend mette la spiegazione nel campo 'detail' di FastAPI; se manca
    si ripiega sul testo grezzo, che e' comunque piu' utile del solo codice.
    """
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"

    if isinstance(payload, dict) and "detail" in payload:
        return f"HTTP {response.status_code}: {payload['detail']}"
    return f"HTTP {response.status_code}"


def api_call(method: str, path: str, *, params: Optional[dict] = None,
             json_body: Optional[dict] = None,
             timeout: int = TIMEOUT_SHORT) -> tuple[Optional[Any], Optional[str]]:
    """
    Chiama il backend restituendo (dati, errore).

    Nessuna eccezione esce da qui: la UI deve poter mostrare l'errore
    all'utente, che e' un requisito esplicito della consegna, invece di
    restituire una pagina di errore del server.
    """
    url = f"{API_BASE_URL}{path}"
    try:
        response = requests.request(method, url, params=params, json=json_body, timeout=timeout)
    except requests.Timeout:
        return None, f"Il backend non ha risposto entro {timeout} secondi."
    except requests.RequestException as exc:
        return None, f"Backend non raggiungibile: {exc}"

    if response.status_code >= 400:
        return None, _error_message(response)

    try:
        return response.json(), None
    except ValueError:
        return None, "Il backend ha restituito una risposta non JSON."


def load_domains() -> tuple[list[str], Optional[str]]:
    """Domini supportati, usati in quasi tutte le pagine."""
    data, error = api_call("GET", "/domains")
    if error:
        return [], error
    return data.get("domains", []), None


def load_gs_urls(domain: str) -> list[str]:
    """URL del Gold Standard di un dominio; lista vuota se qualcosa va storto."""
    data, error = api_call("GET", "/gold_standard_urls", params={"domain": domain})
    return data.get("gold_standard_urls", []) if not error else []


def load_web_resource_urls(domain: str) -> list[str]:
    """URL gia' scaricati per un dominio, con o senza testo di riferimento."""
    data, error = api_call("GET", "/web_resource_urls", params={"domain": domain})
    return data.get("web_resource_urls", []) if not error else []


def load_all_gs_urls(domains: list[str]) -> list[str]:
    """URL del Gold Standard di tutti i domini, per il menu a tendina."""
    urls: list[str] = []
    for domain in domains:
        urls.extend(load_gs_urls(domain))
    return urls


def render(request: Request, template: str, **context: Any) -> HTMLResponse:
    """Rende un template passando sempre il contesto comune a tutte le pagine."""
    context.setdefault("error", None)
    context.setdefault("message", None)
    # Valori di riserva: un template non deve rompersi solo perche' una via
    # d'errore ha passato meno contesto di quella normale.
    context.setdefault("gs_urls", [])
    context.setdefault("pending_urls", [])
    context.setdefault("fetched", None)
    context.setdefault("fetched_url", "")
    context.setdefault("from_db", False)
    return templates.TemplateResponse(request, template, {"request": request, **context})


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """Stato del sistema, domini supportati e navigazione."""
    domains, domains_error = load_domains()
    status, status_error = api_call("GET", "/status")

    errors = [e for e in (domains_error, status_error) if e]

    return render(
        request, "home.html",
        domains=domains,
        status=status or {"backend": "error", "database": "error", "ollama": "error"},
        matricole=MATRICOLE,
        error=" | ".join(errors) if errors else None,
    )


# ---------------------------------------------------------------------------
# Parser & Evaluation
# ---------------------------------------------------------------------------

@app.get("/parser", response_class=HTMLResponse)
def parser_page(request: Request) -> HTMLResponse:
    """Form vuoto per provare un parser."""
    domains, error = load_domains()
    return render(
        request, "parser.html",
        domains=domains,
        gs_urls=load_all_gs_urls(domains),
        mode="live",
        error=error,
    )


@app.post("/parser", response_class=HTMLResponse)
def parser_run(request: Request,
               url: str = Form(""),
               gs_url: str = Form(""),
               mode: str = Form("live")) -> HTMLResponse:
    """
    Esegue il parsing e, se l'URL e' nel Gold Standard, anche la valutazione.

    L'URL scelto dal menu a tendina ha la precedenza su quello digitato: se
    l'utente ne seleziona uno, e' quello che vuole provare.
    """
    domains, _ = load_domains()
    gs_urls = load_all_gs_urls(domains)

    target = (gs_url or url).strip()
    if not target:
        return render(request, "parser.html", domains=domains, gs_urls=gs_urls, mode=mode,
                      error="Inserisci un URL oppure selezionane uno dal menu.")

    local = mode == "local"
    parse_result, parse_error = api_call(
        "POST", "/parse",
        json_body={"url": target, "local": local},
        timeout=TIMEOUT_SHORT if local else TIMEOUT_LONG,
    )

    if parse_error:
        return render(request, "parser.html", domains=domains, gs_urls=gs_urls,
                      submitted_url=target, mode=mode, error=parse_error)

    # Il gold standard puo' non esserci: e' un caso normale, non un errore.
    gold_result, _ = api_call("GET", "/gold_standard", params={"url": target})

    eval_result = judge_result = None
    eval_errors: list[str] = []

    if gold_result:
        payload = {
            "parsed_text": parse_result.get("parsed_text", ""),
            "gold_text": gold_result.get("gold_text", ""),
        }

        eval_result, eval_error = api_call("POST", "/evaluate", json_body=payload)
        if eval_error:
            eval_errors.append(f"Metriche: {eval_error}")

        judge_result, judge_error = api_call("POST", "/evaluate_judge", json_body=payload,
                                             timeout=TIMEOUT_LONG)
        if judge_error:
            eval_errors.append(f"Judge: {judge_error}")

    return render(
        request, "parser.html",
        domains=domains,
        gs_urls=gs_urls,
        submitted_url=target,
        mode=mode,
        parse_result=parse_result,
        gold_result=gold_result,
        eval_result=eval_result,
        judge_result=judge_result,
        error=" | ".join(eval_errors) if eval_errors else None,
    )


# ---------------------------------------------------------------------------
# Gold Standard Builder
# ---------------------------------------------------------------------------

@app.get("/gold-standard", response_class=HTMLResponse)
def gold_standard_page(request: Request, domain: str = "") -> HTMLResponse:
    """Elenco delle entry di un dominio e form per aggiungerne una."""
    domains, error = load_domains()
    selected = domain or (domains[0] if domains else "")

    gs_urls = load_gs_urls(selected) if selected else []
    all_urls = load_web_resource_urls(selected) if selected else []

    return render(
        request, "gold_standard.html",
        domains=domains,
        selected_domain=selected,
        gs_urls=gs_urls,
        # Pagine gia' scaricate a cui manca solo il testo di riferimento.
        pending_urls=[u for u in all_urls if u not in gs_urls],
        error=error,
    )


@app.post("/gold-standard/fetch", response_class=HTMLResponse)
def gold_standard_fetch(request: Request,
                        domain: str = Form(...),
                        url: str = Form(""),
                        db_url: str = Form(""),
                        source: str = Form("live")) -> HTMLResponse:
    """
    Prepara una pagina per la scrittura del testo di riferimento.

    Due sorgenti possibili:

      live  scarica la pagina adesso. E' la via normale per aggiungere un URL
            nuovo.
      db    riusa l'HTML gia' salvato in web_resources. Serve alle pagine
            caricate dai JSON all'avvio e, soprattutto, ai domini che
            rifiutano le richieste automatiche: li' un nuovo download
            restituirebbe una pagina di errore e sovrascriverebbe l'HTML buono.
    """
    domains, _ = load_domains()
    use_db = source == "db"
    target = (db_url if use_db else url).strip()

    if not target:
        gs_urls = load_gs_urls(domain)
        return render(request, "gold_standard.html", domains=domains,
                      selected_domain=domain, gs_urls=gs_urls,
                      pending_urls=[u for u in load_web_resource_urls(domain) if u not in gs_urls],
                      error="Indica un URL da scaricare oppure scegline uno gia' nel database.")

    parse_result, error = api_call("POST", "/parse",
                                   json_body={"url": target, "local": use_db},
                                   timeout=TIMEOUT_SHORT if use_db else TIMEOUT_LONG)

    gs_urls = load_gs_urls(domain)
    return render(
        request, "gold_standard.html",
        domains=domains,
        selected_domain=domain,
        gs_urls=gs_urls,
        pending_urls=[u for u in load_web_resource_urls(domain) if u not in gs_urls],
        fetched_url=target,
        fetched=parse_result,
        from_db=use_db,
        error=error,
    )


@app.post("/gold-standard/save", response_class=HTMLResponse)
def gold_standard_save(request: Request,
                       domain: str = Form(...),
                       url: str = Form(...),
                       html_text: str = Form(...),
                       gold_text: str = Form(...)) -> HTMLResponse:
    """
    Salva insieme la risorsa web e il suo testo di riferimento.

    L'ordine non e' negoziabile: la foreign key impone che la risorsa web
    esista prima del gold standard. Se il primo passo fallisce ci si ferma,
    perche' il secondo fallirebbe comunque con un errore meno chiaro.
    """
    domains, _ = load_domains()
    url = url.strip()

    _, resource_error = api_call("POST", "/add_web_resource",
                                 json_body={"url": url, "html_text": html_text},
                                 timeout=TIMEOUT_LONG)
    if resource_error:
        return render(request, "gold_standard.html", domains=domains,
                      selected_domain=domain, gs_urls=load_gs_urls(domain),
                      error=f"Salvataggio della risorsa web fallito: {resource_error}")

    _, gold_error = api_call("POST", "/add_gold_standard",
                             json_body={"url": url, "gold_text": gold_text})
    if gold_error:
        return render(request, "gold_standard.html", domains=domains,
                      selected_domain=domain, gs_urls=load_gs_urls(domain),
                      error=f"Salvataggio del gold standard fallito: {gold_error}")

    gs_urls = load_gs_urls(domain)
    return render(request, "gold_standard.html", domains=domains,
                  selected_domain=domain, gs_urls=gs_urls,
                  pending_urls=[u for u in load_web_resource_urls(domain) if u not in gs_urls],
                  message=f"Salvato: {url}")


@app.post("/gold-standard/delete", response_class=HTMLResponse)
def gold_standard_delete(request: Request,
                         domain: str = Form(...),
                         url: str = Form(...),
                         scope: str = Form("gold")) -> HTMLResponse:
    """
    Rimuove il solo gold standard oppure l'intera risorsa web.

    Due pulsanti distinti perche' sono due operazioni diverse: cancellare la
    risorsa web porta via anche il gold standard, a cascata.
    """
    domains, _ = load_domains()
    path = "/web_resource" if scope == "resource" else "/gold_standard"

    _, error = api_call("DELETE", path, json_body={"url": url})

    gs_urls = load_gs_urls(domain)
    return render(request, "gold_standard.html", domains=domains,
                  selected_domain=domain, gs_urls=gs_urls,
                  pending_urls=[u for u in load_web_resource_urls(domain) if u not in gs_urls],
                  message=None if error else f"Rimosso ({path}): {url}",
                  error=error)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request) -> HTMLResponse:
    """Panoramica aggregata di tutti i domini in un'unica vista."""
    stats, error = api_call("GET", "/db_stats", timeout=TIMEOUT_LONG)
    schema, schema_error = api_call("GET", "/db_schema")

    errors = [e for e in (error, schema_error) if e]
    domains = sorted((stats or {}).get("web_resources", {}).keys())

    return render(
        request, "stats.html",
        stats=stats,
        schema=schema,
        domains=domains,
        error=" | ".join(errors) if errors else None,
    )


@app.get("/health")
def health() -> RedirectResponse:
    """Comodita' per il debug: rimanda alla home."""
    return RedirectResponse(url="/")
