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
import time
from dataclasses import dataclass
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

# La barra laterale mostra stato del sistema e domini su ogni pagina: due
# chiamate REST in piu' per ogni richiesta. Il timeout e' corto perche' una
# barra laterale non deve mai far aspettare la pagina, e il risultato resta in
# cache per pochi secondi: i domini arrivano da un file di configurazione e
# cambiano solo al riavvio del backend, lo stato non ha bisogno di essere piu'
# fresco di cosi'.
TIMEOUT_SIDEBAR = 5
SIDEBAR_TTL = 10.0

_sidebar_cache: dict[str, Any] = {"expires": 0.0, "value": None}


@dataclass(frozen=True)
class ApiError:
    """
    Errore di una chiamata al backend, in due pezzi.

    La consegna chiede che l'errore sia mostrato all'utente, non che gli sia
    mostrata l'eccezione di 'requests': 'message' e' la frase che va in pagina,
    'detail' e' il testo tecnico che serve a noi e che la UI tiene richiuso.
    Restando una sola classe, i due pezzi non possono separarsi per strada.
    """

    message: str
    detail: str = ""

    def __str__(self) -> str:
        # Cosi' un ApiError si comporta come la vecchia stringa ovunque venga
        # interpolato, senza dover riscrivere tutti i punti che lo usano.
        return self.message

    def prefixed(self, label: str) -> "ApiError":
        """Stesso errore, con l'indicazione di quale passo e' fallito."""
        return ApiError(f"{label}: {self.message}", self.detail)


def merge_errors(*errors: Optional[Any]) -> Optional[ApiError]:
    """
    Fonde piu' errori in uno solo, senza ripetizioni.

    La home interroga /status e /domains: se il backend e' spento falliscono
    tutte e due per lo stesso motivo, e scrivere due volte la stessa frase non
    aggiunge niente per chi legge.
    """
    real = [e for e in errors if e]
    if not real:
        return None

    messages: list[str] = []
    details: list[str] = []
    for error in real:
        message = error.message if isinstance(error, ApiError) else str(error)
        detail = error.detail if isinstance(error, ApiError) else ""
        if message not in messages:
            messages.append(message)
        if detail and detail not in details:
            details.append(detail)

    return ApiError(" | ".join(messages), "\n".join(details))


def _error_detail(response: requests.Response) -> str:
    """
    Spiegazione tecnica ricavata dalla risposta del backend.

    Il backend mette il motivo nel campo 'detail' di FastAPI; se manca si
    ripiega sul corpo grezzo, che e' comunque piu' utile del solo codice.
    """
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]

    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])
    return response.text[:500]


def api_call(method: str, path: str, *, params: Optional[dict] = None,
             json_body: Optional[dict] = None,
             timeout: int = TIMEOUT_SHORT) -> tuple[Optional[dict], Optional[ApiError]]:
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
        return None, ApiError(
            f"Il backend non ha risposto entro {timeout} secondi.",
            f"Timeout su {method} {url}",
        )
    except requests.RequestException as exc:
        return None, ApiError(
            f"Backend non raggiungibile all'indirizzo {API_BASE_URL}.",
            f"{method} {url}\n{type(exc).__name__}: {exc}",
        )

    if response.status_code >= 400:
        return None, ApiError(
            f"Il backend ha risposto con un errore (HTTP {response.status_code}).",
            f"{method} {url}\n{_error_detail(response)}",
        )

    try:
        return response.json(), None
    except ValueError:
        return None, ApiError(
            "Il backend ha restituito una risposta non JSON.",
            f"{method} {url}\n{response.text[:500]}",
        )


def sidebar_state(refresh: bool = False) -> dict[str, Any]:
    """
    Stato dei componenti e domini supportati, per la barra laterale.

    Unico punto in cui la UI chiede queste due informazioni: le pagine che ne
    hanno bisogno passano di qui, cosi' una richiesta non le domanda mai due
    volte al backend.
    """
    now = time.monotonic()
    cached = _sidebar_cache["value"]
    if cached is not None and not refresh and now < _sidebar_cache["expires"]:
        return cached

    status, status_error = api_call("GET", "/status", timeout=TIMEOUT_SIDEBAR)
    domains_data, domains_error = api_call("GET", "/domains", timeout=TIMEOUT_SIDEBAR)

    state: dict[str, Any] = {
        "status": status or {"backend": "error", "database": "error", "ollama": "error"},
        "domains": (domains_data or {}).get("domains", []),
        "status_error": status_error,
        "domains_error": domains_error,
    }
    _sidebar_cache["value"] = state
    _sidebar_cache["expires"] = now + SIDEBAR_TTL
    return state


def load_domains() -> tuple[list[str], Optional[ApiError]]:
    """Domini supportati, usati in quasi tutte le pagine."""
    state = sidebar_state()
    return state["domains"], state["domains_error"]


def load_gs_urls(domain: str) -> list[str]:
    """URL del Gold Standard di un dominio; lista vuota se qualcosa va storto."""
    data, error = api_call("GET", "/gold_standard_urls", params={"domain": domain})
    if error or data is None:
        return []
    return data.get("gold_standard_urls", [])


def load_web_resource_urls(domain: str) -> list[str]:
    """URL gia' scaricati per un dominio, con o senza testo di riferimento."""
    data, error = api_call("GET", "/web_resource_urls", params={"domain": domain})
    if error or data is None:
        return []
    return data.get("web_resource_urls", [])


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

    # La barra laterale e' identica su tutte le pagine: il suo contesto lo
    # mette qui il render, non ogni singola vista.
    state = sidebar_state()
    context.setdefault("sidebar_status", state["status"])
    context.setdefault("sidebar_domains", state["domains"])
    context.setdefault("matricole", MATRICOLE)
    return templates.TemplateResponse(request, template, {"request": request, **context})


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """Stato del sistema, domini supportati e navigazione."""
    # Ricaricare la home e' il modo naturale di chiedere "com'e' messo adesso
    # il sistema?": qui la cache si scavalca e i dati sono sempre freschi.
    state = sidebar_state(refresh=True)

    return render(
        request, "home.html",
        domains=state["domains"],
        status=state["status"],
        sidebar_status=state["status"],
        sidebar_domains=state["domains"],
        error=merge_errors(state["domains_error"], state["status_error"]),
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

    # Il controllo esplicito su None non e' ridondante: api_call restituisce
    # (dati, errore) e solo uno dei due e' valorizzato. Scriverlo qui evita che
    # il resto della funzione lavori su un valore che potrebbe non esserci.
    if parse_error or parse_result is None:
        return render(request, "parser.html", domains=domains, gs_urls=gs_urls,
                      submitted_url=target, mode=mode,
                      error=parse_error or "Il backend non ha restituito nessun risultato.")

    # Il gold standard puo' non esserci: e' un caso normale, non un errore.
    gold_result, _ = api_call("GET", "/gold_standard", params={"url": target})

    eval_result = judge_result = None
    eval_errors: list[ApiError] = []

    if gold_result:
        payload = {
            "parsed_text": parse_result.get("parsed_text", ""),
            "gold_text": gold_result.get("gold_text", ""),
        }

        eval_result, eval_error = api_call("POST", "/evaluate", json_body=payload)
        if eval_error:
            eval_errors.append(eval_error.prefixed("Metriche"))

        judge_result, judge_error = api_call("POST", "/evaluate_judge", json_body=payload,
                                             timeout=TIMEOUT_LONG)
        if judge_error:
            eval_errors.append(judge_error.prefixed("Judge"))

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
        error=merge_errors(*eval_errors),
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

    def page(**extra):
        gs_urls = load_gs_urls(domain)
        return render(request, "gold_standard.html", domains=domains,
                      selected_domain=domain, gs_urls=gs_urls,
                      pending_urls=[u for u in load_web_resource_urls(domain) if u not in gs_urls],
                      **extra)

    if not target:
        return page(error="Indica un URL da scaricare oppure scegline uno gia' nel database.")

    parse_result, error = api_call("POST", "/parse",
                                   json_body={"url": target, "local": use_db},
                                   timeout=TIMEOUT_SHORT if use_db else TIMEOUT_LONG)
    if error or parse_result is None:
        return page(fetched_url=target, from_db=use_db,
                    error=error or "Il backend non ha restituito nessun risultato.")

    # La risorsa web viene salvata subito, non al momento del submit.
    #
    # Cosi' l'HTML fa un solo viaggio, dal backend al database, e non deve
    # tornare al browser dentro un campo nascosto per essere rispedito con il
    # gold_text: su una pagina da mezzo milione di caratteri quel campo supera
    # il limite del parser multipart e il salvataggio fallisce.
    #
    # In modalita' 'db' la risorsa e' gia' li' e non si tocca: riscriverla con
    # un nuovo download sarebbe anzi dannoso sui domini che rifiutano le
    # richieste automatiche.
    if not use_db:
        _, save_error = api_call("POST", "/add_web_resource",
                                 json_body={"url": parse_result["url"],
                                            "html_text": parse_result["html_text"]},
                                 timeout=TIMEOUT_LONG)
        if save_error:
            return page(fetched_url=target,
                        error=save_error.prefixed("Pagina scaricata ma non salvata nel database"))

    return page(fetched_url=target, fetched=parse_result, from_db=use_db)


# Limite per singolo campo del form. Il default di python-multipart e' 1 MB,
# che basta per un gold_text ma non per un HTML: se per qualunque motivo un
# campo grande arriva lo stesso, meglio accettarlo che rispondere con un
# errore che l'utente non puo' interpretare.
MAX_FORM_FIELD_BYTES = 8 * 1024 * 1024


async def read_form(request: Request) -> dict:
    """
    Legge i campi del form alzando il limite di dimensione per campo.

    Non si usano i parametri Form() di FastAPI perche' non permettono di
    configurare quel limite: la richiesta verrebbe rifiutata prima ancora di
    arrivare al gestore, con un errore grezzo al posto della pagina.

    Il parametro max_part_size non esiste nelle versioni piu' vecchie di
    Starlette: in quel caso si ripiega sulla lettura normale.
    """
    try:
        form = await request.form(max_part_size=MAX_FORM_FIELD_BYTES)
    except TypeError:
        form = await request.form()
    return {key: str(value) for key, value in form.items()}


@app.post("/gold-standard/save", response_class=HTMLResponse)
async def gold_standard_save(request: Request) -> HTMLResponse:
    """
    Salva il testo di riferimento di una pagina gia' presente nel database.

    Il form invia solo url e gold_text. L'HTML e' stato scritto in
    web_resources al momento del download, quindi non serve rimandarlo: era
    l'unico campo che poteva superare il limite di dimensione di una parte
    multipart, e su una pagina grande faceva fallire il salvataggio.

    Il vincolo di integrita' referenziale resta soddisfatto lo stesso: la
    risorsa web esiste gia' quando si arriva qui.
    """
    fields = await read_form(request)
    domain = fields.get("domain", "")
    url = fields.get("url", "").strip()
    gold_text = fields.get("gold_text", "")

    domains, _ = load_domains()

    def page(**extra):
        gs_urls = load_gs_urls(domain)
        return render(request, "gold_standard.html", domains=domains,
                      selected_domain=domain, gs_urls=gs_urls,
                      pending_urls=[u for u in load_web_resource_urls(domain) if u not in gs_urls],
                      **extra)

    if not gold_text.strip():
        return page(error="Il testo di riferimento e' vuoto: incolla il testo copiato dalla pagina.")

    _, gold_error = api_call("POST", "/add_gold_standard",
                             json_body={"url": url, "gold_text": gold_text})
    if gold_error:
        return page(error=gold_error.prefixed("Salvataggio del gold standard fallito"))

    return page(message=f"Salvato: {url}")


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

def stats_summary(stats: Optional[dict], domains: list[str]) -> dict[str, Any]:
    """
    Quattro numeri di sintesi per i riquadri in cima alla pagina.

    Il conto si fa qui e non nel template: una media dentro un ciclo Jinja e'
    illeggibile, e le medie per dominio le calcola gia' il backend.
    """
    if not stats:
        return {"resources": 0, "gold": 0, "f1": None, "judge": None}

    f1_values = [
        stats.get("avg_eval", {}).get(d, {}).get("token_level_eval", {}).get("f1")
        for d in domains
    ]
    f1_values = [v for v in f1_values if v is not None]

    judge_values = [
        stats.get("avg_eval_judge", {}).get(d, {}).get("judge_score")
        for d in domains
    ]
    judge_values = [v for v in judge_values if v]

    return {
        "resources": sum(stats.get("web_resources", {}).values()),
        "gold": sum(stats.get("gold_standard", {}).values()),
        # Media delle medie: i domini hanno lo stesso numero di entry, quindi
        # coincide con la media generale.
        "f1": sum(f1_values) / len(f1_values) if f1_values else None,
        "judge": sum(judge_values) / len(judge_values) if judge_values else None,
    }


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request) -> HTMLResponse:
    """Panoramica aggregata di tutti i domini in un'unica vista."""
    stats, error = api_call("GET", "/db_stats", timeout=TIMEOUT_LONG)
    schema, schema_error = api_call("GET", "/db_schema")

    domains = sorted((stats or {}).get("web_resources", {}).keys())

    return render(
        request, "stats.html",
        stats=stats,
        schema=schema,
        domains=domains,
        summary=stats_summary(stats, domains),
        error=merge_errors(error, schema_error),
    )


@app.get("/health")
def health() -> RedirectResponse:
    """Comodita' per il debug: rimanda alla home."""
    return RedirectResponse(url="/")
