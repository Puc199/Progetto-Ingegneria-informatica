"""
Modelli Pydantic di ingresso e uscita delle API.

Ogni endpoint dichiara il proprio response_model: la validazione non e' una
formalita', e' cio' che garantisce che il JSON restituito abbia esattamente
i campi della specifica, visto che i formati vengono verificati da uno script
di test automatico.

Nota sugli URL: sono dichiarati 'str' e non 'HttpUrl'. HttpUrl normalizza il
valore (per esempio aggiunge lo slash finale a "https://esempio.it"), e un
URL normalizzato non corrisponderebbe piu' alla chiave salvata nel database.
Qui l'URL e' una chiave primaria, quindi deve tornare indietro identico a
come e' arrivato. La validazione dello schema si fa a parte, con un
controllo esplicito.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class ParseRequest(BaseModel):
    """Corpo di POST /parse."""

    url: str
    local: Optional[bool] = Field(
        default=False,
        description="Se vero usa l'HTML gia' salvato nel database invece di scaricare la pagina.",
    )


class ParseHtmlRequest(BaseModel):
    """
    Corpo della variante dell'esonero, mantenuta per compatibilita':
    esegue il parsing su un HTML fornito direttamente dal chiamante.
    """

    url: str
    html_text: str


class ParseResponse(BaseModel):
    url: str
    domain: str
    title: str
    html_text: str
    parsed_text: str


class DomainsResponse(BaseModel):
    domains: List[str]


# ---------------------------------------------------------------------------
# Gold Standard
# ---------------------------------------------------------------------------

class GoldStandardEntry(BaseModel):
    url: str
    domain: str
    title: str
    html_text: str
    gold_text: str


class FullGoldStandardResponse(BaseModel):
    gold_standard: List[GoldStandardEntry]


class GoldStandardUrlsResponse(BaseModel):
    gold_standard_urls: List[str]


class WebResourceUrlsResponse(BaseModel):
    """
    URL presenti in web_resources per un dominio.

    Non e' fra gli endpoint richiesti dalla specifica: e' un'aggiunta che
    serve alla pagina di costruzione del Gold Standard per sapere quali
    pagine sono gia' scaricate e attendono solo il testo di riferimento.
    """

    web_resource_urls: List[str]


# ---------------------------------------------------------------------------
# Valutazione
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    parsed_text: str
    gold_text: str


class MetricScores(BaseModel):
    precision: float
    recall: float
    f1: float


class EvaluateResponse(BaseModel):
    """
    Risultato delle metriche automatiche.

    token_level_eval e' obbligatoria; le altre metriche implementate
    compaiono come chiavi aggiuntive dello stesso oggetto.
    """

    token_level_eval: MetricScores
    sequence_eval: Optional[MetricScores] = None


class EvaluateJudgeResponse(BaseModel):
    """
    Risultato del giudizio dell'LLM.

    model_name, judge_score e judge_feedback sono obbligatori. parse_ok e'
    un'aggiunta nostra: dice se il modello ha rispettato il formato JSON o se
    e' entrato in funzione il fallback.
    """

    model_name: str
    judge_score: int
    judge_feedback: str
    parse_ok: bool = True


class FullGSEvalResponse(BaseModel):
    """Valutazione aggregata su tutto il Gold Standard di un dominio."""

    token_level_eval: MetricScores
    sequence_eval: Optional[MetricScores] = None
    judge_score: float
    evaluated_entries: int


# ---------------------------------------------------------------------------
# Gestione dei dati nel database
# ---------------------------------------------------------------------------

class AddWebResourceRequest(BaseModel):
    url: str
    html_text: str


class AddGoldStandardRequest(BaseModel):
    url: str
    gold_text: str


class UrlRequest(BaseModel):
    """Corpo delle DELETE, che identificano la riga da rimuovere con l'URL."""

    url: str


class StatusResponse(BaseModel):
    """
    Esito di un'operazione di scrittura.

    La specifica prevede "ok" oppure "error"; detail viene aggiunto solo
    quando c'e' qualcosa di utile da spiegare.
    """

    status: str
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# Introspezione del sistema
# ---------------------------------------------------------------------------

class DbStatsResponse(BaseModel):
    web_resources: Dict[str, int]
    gold_standard: Dict[str, int]
    avg_eval: Dict[str, Dict[str, Dict[str, float]]]
    avg_eval_judge: Dict[str, Dict[str, float]]


# GET /db_schema restituisce le tabelle al primo livello dell'oggetto, senza
# involucri: i nomi non sono noti a priori, quindi il tipo di risposta e' un
# semplice dizionario annidato invece di un modello con campi fissi.
DbSchema = Dict[str, Dict[str, str]]


class SystemStatusResponse(BaseModel):
    """
    Stato dei componenti. Ogni valore e' "ok" oppure "error".

    L'endpoint risponde sempre con HTTP 200: e' il contenuto del JSON a dire
    se qualcosa non funziona, non il codice di stato.
    """

    backend: str
    database: str
    ollama: str
