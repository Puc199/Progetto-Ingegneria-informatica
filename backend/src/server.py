"""
API REST del progetto.

Questo modulo e' volutamente sottile: riceve la richiesta, sceglie il parser
o interroga il repository, traduce gli errori in codici HTTP e restituisce un
modello Pydantic. Tutta la logica sta altrove, in src/parsers/ e in
src/services/.

Ogni endpoint dichiara response_model: e' cio' che garantisce che il JSON
abbia esattamente i campi della specifica, che viene verificata da uno script
di test automatico.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException, Query

from src.parsers.base_parser import extract_page_title, make_soup
from src.parsers.registry import get_domain, get_parser
from src.schemas import (
    AddGoldStandardRequest,
    AddWebResourceRequest,
    DbSchema,
    DbStatsResponse,
    DomainsResponse,
    EvaluateJudgeResponse,
    EvaluateRequest,
    EvaluateResponse,
    FullGoldStandardResponse,
    FullGSEvalResponse,
    GoldStandardEntry,
    GoldStandardUrlsResponse,
    ParseHtmlRequest,
    ParseRequest,
    ParseResponse,
    StatusResponse,
    SystemStatusResponse,
    UrlRequest,
    WebResourceUrlsResponse,
)
from src.services import bootstrap, database, repository
from src.services.evaluator import evaluate_all
from src.services.judge import OLLAMA_MODEL, evaluate_judge, judge_available

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Pipeline di Parsing Web")

BASE_DIR = Path(__file__).resolve().parents[1]      # /app nel Docker, backend/ in locale


def _resolve(name: str) -> Path:
    """Cerca file e cartelle accanto a src/ (Docker) e nella root del progetto (locale)."""
    for candidate in (BASE_DIR / name, BASE_DIR.parent / name):
        if candidate.exists():
            return candidate
    return BASE_DIR / name


DOMAINS_FILE = _resolve("domains.json")
GS_DATA_DIR = _resolve("gs_data")


@app.on_event("startup")
def on_startup() -> None:
    """
    Inizializzazione automatica del sistema.

    La consegna vieta passaggi intermedi fra "docker compose up --build" e lo
    script di test: schema, dati e metriche devono essere pronti da soli.
    Un errore qui non deve impedire l'avvio, altrimenti GET /status non
    potrebbe nemmeno riportare che il database non risponde.
    """
    try:
        summary = bootstrap.initialize(GS_DATA_DIR)
        logger.info("Inizializzazione completata: %s", summary)
    except Exception as exc:
        logger.exception("Inizializzazione fallita: %s", exc)


# ---------------------------------------------------------------------------
# Utilita' condivise
# ---------------------------------------------------------------------------

def load_domains() -> list[str]:
    """Domini supportati, letti da domains.json."""
    try:
        domains = json.loads(DOMAINS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="File domains.json non trovato.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="domains.json non e' un JSON valido.")

    if not isinstance(domains, list):
        raise HTTPException(status_code=500, detail="domains.json deve contenere una lista.")

    return [d.strip() for d in domains if isinstance(d, str) and d.strip()]


def normalize_domain(domain: str) -> str:
    """Dominio senza 'www.' e in minuscolo, per confronti tolleranti."""
    domain = (domain or "").strip().lower()
    return domain[4:] if domain.startswith("www.") else domain


def canonical_domain(url: str) -> str:
    """
    Dominio da memorizzare per un URL, nella forma dichiarata in domains.json.

    Serve perche' 'www.basketball-reference.com' e 'basketball-reference.com'
    sono lo stesso sito ma due stringhe diverse: se una risorsa venisse salvata
    con la seconda forma, le query per dominio — che usano quella di
    domains.json — non la troverebbero piu'. Si confronta quindi in forma
    normalizzata e si restituisce la grafia dichiarata.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return ""

    normalized = normalize_domain(host)
    for declared in load_domains():
        if normalize_domain(declared) == normalized:
            return declared
    return host


def require_supported_domain(domain: str) -> str:
    """
    Verifica che il dominio sia fra quelli assegnati.

    Raises:
        HTTPException 400: se il dominio non e' supportato.
    """
    normalized = normalize_domain(domain)
    supported = {normalize_domain(d) for d in load_domains()}

    if normalized not in supported:
        raise HTTPException(status_code=400, detail=f"Dominio non supportato: {domain}")
    return normalized


def require_parser(url: str):
    """
    Restituisce il parser adatto all'URL.

    Raises:
        HTTPException 400: se nessun parser copre quel dominio.
    """
    parser, domain = get_parser(url)
    if parser is None:
        raise HTTPException(status_code=400, detail=f"Dominio non supportato: {domain or url}")
    return parser, domain


def run_parser(parser, url: str, html_text: Optional[str] = None) -> dict:
    """
    Esegue un parser traducendo i suoi errori in codici HTTP.

    Raises:
        HTTPException 502: se il parser non riesce a produrre un risultato,
                           tipicamente perche' l'URL e' irraggiungibile.
    """
    try:
        result = parser(url, html_text=html_text)
    except Exception as exc:
        logger.error("Parsing fallito su %s: %s", url, exc)
        raise HTTPException(status_code=502, detail=f"URL irraggiungibile o parsing fallito: {exc}")

    if not isinstance(result, dict) or "parsed_text" not in result:
        raise HTTPException(status_code=500, detail="Il parser non ha restituito un risultato valido.")

    return result


def _to_parse_response(result: dict) -> ParseResponse:
    """Riduce il risultato del parser ai soli campi previsti dalla specifica."""
    return ParseResponse(**{key: result.get(key) or "" for key in ParseResponse.model_fields})


def _to_gs_entry(entry: dict) -> GoldStandardEntry:
    """Converte una riga del database in una entry del Gold Standard."""
    return GoldStandardEntry(**{key: entry.get(key) or "" for key in GoldStandardEntry.model_fields})


# ---------------------------------------------------------------------------
# Obiettivo 1 e 6: parsing
# ---------------------------------------------------------------------------

@app.post("/parse", response_model=ParseResponse)
def parse_post(body: ParseRequest) -> ParseResponse:
    """
    Esegue il parser adatto al dominio dell'URL.

    Con local=true si usa l'HTML gia' salvato in web_resources e non si
    scarica nulla: e' la modalita' che rende ripetibile la valutazione su
    siti che cambiano da un giorno all'altro.
    """
    parser, _ = require_parser(body.url)

    html_text: Optional[str] = None
    if body.local:
        resource = repository.get_web_resource(body.url)
        if resource is None:
            raise HTTPException(status_code=404,
                                detail=f"URL non presente nel database: {body.url}")
        html_text = resource["html_text"]

    return _to_parse_response(run_parser(parser, body.url, html_text))


@app.get("/parse", response_model=ParseResponse)
def parse_get(url: str = Query(...), local: bool = Query(False)) -> ParseResponse:
    """Variante GET, mantenuta dall'esonero: stesso comportamento di POST /parse."""
    return parse_post(ParseRequest(url=url, local=local))


@app.post("/parse_html", response_model=ParseResponse)
def parse_html(body: ParseHtmlRequest) -> ParseResponse:
    """
    Esegue il parser su un HTML fornito dal chiamante.

    Serve alla Web UI per mostrare il parsing di una pagina appena scaricata
    senza doverla prima salvare nel database.
    """
    parser, _ = require_parser(body.url)
    return _to_parse_response(run_parser(parser, body.url, body.html_text))


@app.get("/domains", response_model=DomainsResponse)
def get_domains() -> DomainsResponse:
    """Elenco dei domini supportati dal sistema."""
    return DomainsResponse(domains=load_domains())


# ---------------------------------------------------------------------------
# Obiettivo 2 e 6: gold standard
# ---------------------------------------------------------------------------

@app.get("/gold_standard", response_model=GoldStandardEntry)
def get_gold_standard(url: str = Query(...)) -> GoldStandardEntry:
    """
    Entry del Gold Standard per un URL, letta dal database.

    L'ordine dei due controlli non e' indifferente. Si cerca prima la riga: se
    c'e', la si restituisce, qualunque sia il dominio. Il vincolo sui domini
    supportati si applica solo quando la riga non esiste, per distinguere
    "dominio che questo sistema non gestisce" (400) da "pagina che non ho"
    (404).

    Il motivo e' che POST /add_web_resource accetta qualunque URL — lo prevede
    la specifica, ed e' cio' che permette ai test di inserire pagine di prova.
    Rifiutare poi la lettura di una riga che il sistema stesso ha accettato di
    scrivere sarebbe incoerente.
    """
    entry = repository.get_gold_standard_entry(url)
    if entry is not None:
        return _to_gs_entry(entry)

    require_supported_domain(get_domain(url))
    raise HTTPException(status_code=404, detail=f"URL non presente nel Gold Standard: {url}")


@app.get("/gold_standard_urls", response_model=GoldStandardUrlsResponse)
def get_gold_standard_urls(domain: str = Query(...)) -> GoldStandardUrlsResponse:
    """Tutti gli URL del Gold Standard di un dominio."""
    require_supported_domain(domain)
    return GoldStandardUrlsResponse(gold_standard_urls=repository.list_gold_standard_urls(domain))


@app.get("/web_resource_urls", response_model=WebResourceUrlsResponse)
def get_web_resource_urls(domain: str = Query(...)) -> WebResourceUrlsResponse:
    """
    URL gia' presenti in web_resources per un dominio.

    Aggiunto oltre alla specifica: serve alla pagina di costruzione del Gold
    Standard per elencare le pagine gia' scaricate a cui manca solo il testo
    di riferimento, senza doverle riscaricare.
    """
    require_supported_domain(domain)
    return WebResourceUrlsResponse(web_resource_urls=repository.list_web_resource_urls(domain))


@app.get("/full_gold_standard", response_model=FullGoldStandardResponse)
def get_full_gold_standard(domain: str = Query(...)) -> FullGoldStandardResponse:
    """Tutte le entry del Gold Standard di un dominio. Mantenuto dall'esonero."""
    require_supported_domain(domain)
    entries = repository.list_gold_standard_by_domain(domain)
    return FullGoldStandardResponse(gold_standard=[_to_gs_entry(e) for e in entries])


# ---------------------------------------------------------------------------
# Obiettivo 3 e 4: valutazione
# ---------------------------------------------------------------------------

@app.post("/evaluate", response_model=EvaluateResponse)
def evaluate(body: EvaluateRequest) -> EvaluateResponse:
    """
    Metriche automatiche fra testo estratto e testo di riferimento.

    Il Markdown viene rimosso dentro le metriche: si confronta il contenuto,
    non la formattazione.
    """
    return EvaluateResponse(**evaluate_all(body.parsed_text, body.gold_text))


@app.post("/evaluate_judge", response_model=EvaluateJudgeResponse)
def evaluate_judge_endpoint(body: EvaluateRequest) -> EvaluateJudgeResponse:
    """
    Giudizio qualitativo dell'LLM sul testo estratto.

    Non solleva mai per colpa del modello: se Ollama non risponde o non
    rispetta il formato, il judge restituisce il proprio fallback con
    parse_ok a falso. Un LLM lento o poco collaborativo e' un caso previsto,
    non un errore del sistema.
    """
    return EvaluateJudgeResponse(**evaluate_judge(body.parsed_text, body.gold_text))


@app.get("/full_gs_eval", response_model=FullGSEvalResponse)
def full_gs_eval(domain: str = Query(...)) -> FullGSEvalResponse:
    """
    Valutazione aggregata su tutto il Gold Standard di un dominio.

    Parsing e metriche vengono ricalcolati a ogni chiamata sull'HTML statico
    del database, come chiede la specifica. I giudizi dell'LLM vengono invece
    riletti dalla tabella judgements quando ci sono, e calcolati solo per le
    entry che ne sono prive: rigenerarli tutti a ogni chiamata significherebbe
    minuti di attesa su CPU per riottenere, a temperatura 0.1 e a parita' di
    input, gli stessi valori.
    """
    require_supported_domain(domain)

    entries = repository.list_gold_standard_by_domain(domain)
    if not entries:
        raise HTTPException(status_code=404,
                            detail=f"Nessuna entry di Gold Standard per il dominio: {domain}")

    totals: dict[str, dict[str, float]] = {}
    judge_scores: list[float] = []
    evaluated = 0

    for entry in entries:
        url = entry["url"]
        parser, _ = get_parser(url)
        if parser is None:
            continue

        try:
            parsed_text = parser(url, html_text=entry["html_text"]).get("parsed_text", "")
        except Exception as exc:
            logger.error("Parsing fallito su %s durante la valutazione: %s", url, exc)
            continue

        gold_text = entry.get("gold_text") or ""

        for metric_name, scores in evaluate_all(parsed_text, gold_text).items():
            bucket = totals.setdefault(metric_name, {"precision": 0.0, "recall": 0.0, "f1": 0.0})
            for key in bucket:
                bucket[key] += scores[key]

        stored = repository.get_judgement(url, OLLAMA_MODEL)
        if stored is None:
            verdict = evaluate_judge(parsed_text, gold_text)
            repository.save_judgement(url, verdict["model_name"], verdict["judge_score"],
                                      verdict["judge_feedback"], verdict["parse_ok"])
            judge_scores.append(float(verdict["judge_score"]))
        else:
            judge_scores.append(float(stored["judge_score"]))

        evaluated += 1

    if not evaluated:
        raise HTTPException(status_code=500,
                            detail=f"Impossibile valutare il Gold Standard del dominio {domain}.")

    averages = {
        name: {key: value / evaluated for key, value in bucket.items()}
        for name, bucket in totals.items()
    }

    return FullGSEvalResponse(
        token_level_eval=averages["token_level_eval"],
        sequence_eval=averages.get("sequence_eval"),
        judge_score=sum(judge_scores) / len(judge_scores) if judge_scores else 0.0,
        evaluated_entries=evaluated,
    )


# ---------------------------------------------------------------------------
# Obiettivo 5 e 6: gestione dei dati nel database
# ---------------------------------------------------------------------------

@app.post("/add_web_resource", response_model=StatusResponse)
def add_web_resource(body: AddWebResourceRequest) -> StatusResponse:
    """
    Inserisce o aggiorna una risorsa web con l'HTML fornito.

    Dominio e titolo non sono richiesti in ingresso dalla specifica: il primo
    si ricava dall'URL, il secondo dal tag <title> dell'HTML.
    """
    domain = canonical_domain(body.url)
    if not domain:
        raise HTTPException(status_code=400, detail=f"URL non valido: {body.url}")

    title = extract_page_title(make_soup(body.html_text))

    try:
        repository.upsert_web_resource(body.url, domain, title, body.html_text)
    except Exception as exc:
        logger.error("Inserimento di %s fallito: %s", body.url, exc)
        return StatusResponse(status="error", detail=str(exc))

    return StatusResponse(status="ok")


@app.post("/add_gold_standard", response_model=StatusResponse)
def add_gold_standard(body: AddGoldStandardRequest) -> StatusResponse:
    """
    Inserisce o aggiorna il testo di riferimento di un URL.

    La risorsa web corrispondente deve gia' esistere: e' il vincolo di
    integrita' referenziale fra le due tabelle. Lo si verifica qui per
    restituire un messaggio comprensibile invece di lasciar emergere
    l'errore di foreign key del database.
    """
    if not repository.web_resource_exists(body.url):
        raise HTTPException(
            status_code=404,
            detail=f"URL non presente in web_resources: {body.url}. "
                   "Aggiungere prima la risorsa web con /add_web_resource.",
        )

    try:
        repository.upsert_gold_standard(body.url, body.gold_text)
    except Exception as exc:
        logger.error("Inserimento del gold standard di %s fallito: %s", body.url, exc)
        return StatusResponse(status="error", detail=str(exc))

    return StatusResponse(status="ok")


@app.delete("/web_resource", response_model=StatusResponse)
def delete_web_resource(body: UrlRequest = Body(...)) -> StatusResponse:
    """
    Rimuove una risorsa web e, a cascata, il suo gold standard.

    La cascata non e' scritta qui: la esegue la foreign key ON DELETE
    CASCADE, cosi' l'integrita' e' garantita dal database anche se la riga
    venisse cancellata da un altro client.
    """
    removed = repository.delete_web_resource(body.url)
    if not removed:
        # Cancellare cio' che non c'e' non e' un errore: lo stato richiesto —
        # "questa risorsa non deve esistere" — e' gia' quello del database.
        # Un DELETE idempotente e' anche cio' che ci si aspetta da una API
        # REST, e permette di ripetere una sequenza di test senza doverla
        # ripulire prima.
        return StatusResponse(status="ok", detail=f"URL non presente: {body.url}")
    return StatusResponse(status="ok")


@app.delete("/gold_standard", response_model=StatusResponse)
def delete_gold_standard(body: UrlRequest = Body(...)) -> StatusResponse:
    """
    Rimuove solo il testo di riferimento, lasciando intatta la risorsa web.

    E' la differenza fra questo endpoint e DELETE /web_resource, che invece
    cancella tutto a cascata. Come quello, e' idempotente: se il testo non
    c'e' — per esempio perche' e' gia' stato rimosso dalla cascata di una
    cancellazione precedente — la richiesta ha comunque ottenuto il suo scopo.
    """
    repository.delete_gold_standard(body.url)
    return StatusResponse(status="ok")


# ---------------------------------------------------------------------------
# Obiettivo 6: introspezione del sistema
# ---------------------------------------------------------------------------

@app.get("/db_stats", response_model=DbStatsResponse)
def db_stats() -> DbStatsResponse:
    """
    Statistiche aggregate per dominio.

    Legge solo valori gia' calcolati e salvati: nessun parsing e nessuna
    chiamata all'LLM, come richiede la specifica.
    """
    return DbStatsResponse(**repository.database_stats())


@app.get("/db_schema", response_model=DbSchema)
def db_schema() -> DbSchema:
    """
    Schema del database: tabelle, colonne, tipi, chiavi primarie ed esterne.

    Letto da information_schema e non da una copia scritta a mano, cosi' la
    risposta non puo' divergere dal database reale.
    """
    return database.table_schema()


@app.get("/status", response_model=SystemStatusResponse)
def status() -> SystemStatusResponse:
    """
    Stato dei tre componenti del sistema.

    Risponde sempre con HTTP 200: e' il contenuto del JSON a dire se qualcosa
    non funziona, non il codice di stato. Con un 503 il client non potrebbe
    distinguere "il backend e' irraggiungibile" da "il backend funziona e sta
    segnalando un problema".
    """
    return SystemStatusResponse(
        backend="ok",
        database="ok" if database.is_available() else "error",
        ollama="ok" if judge_available() else "error",
    )
