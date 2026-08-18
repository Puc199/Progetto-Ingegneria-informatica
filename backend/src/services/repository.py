"""
Query del progetto sul database.

Tutte le query stanno qui e nessuna altrove: server.py chiama funzioni con
nomi parlanti e non conosce lo schema. Cosi' una modifica alle tabelle si
riflette in un solo file, e il livello REST resta leggibile.

Ogni valore che arriva da fuori passa dai segnaposto '?', mai
dall'interpolazione di stringa (vedi la nota in database.py).
"""

from __future__ import annotations

from typing import Any, Optional

from src.services.database import execute, execute_many, fetch_all, fetch_one
from src.services.text_utils import normalize_gold_text

# Nome della metrica obbligatoria, usato come chiave in evaluations.
TOKEN_LEVEL = "token_level_eval"


# ---------------------------------------------------------------------------
# web_resources
# ---------------------------------------------------------------------------

def upsert_web_resource(url: str, domain: str, title: str, html_text: str) -> None:
    """
    Inserisce una risorsa web, o ne aggiorna il contenuto se l'URL esiste.

    L'upsert serve a POST /add_web_resource: la consegna dice che i test
    automatici possono alterare questa tabella, quindi reinserire lo stesso
    URL deve aggiornare l'HTML e non fallire con un errore di chiave duplicata.
    """
    execute(
        """
        INSERT INTO web_resources (url, domain, title, html_text)
        VALUES (?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE
            domain = VALUES(domain),
            title = VALUES(title),
            html_text = VALUES(html_text)
        """,
        (url, domain, title, html_text),
    )


def get_web_resource(url: str) -> Optional[dict]:
    """Risorsa web con quell'URL, o None."""
    return fetch_one(
        "SELECT url, domain, title, html_text, created_at FROM web_resources WHERE url = ?",
        (url,),
    )


def web_resource_exists(url: str) -> bool:
    """Vero se l'URL e' gia' in web_resources."""
    return fetch_one("SELECT 1 AS present FROM web_resources WHERE url = ?", (url,)) is not None


def delete_web_resource(url: str) -> int:
    """
    Cancella una risorsa web.

    Il gold standard collegato sparisce da solo: la foreign key e' definita
    ON DELETE CASCADE, quindi l'integrita' referenziale la garantisce il
    database e non il codice applicativo.
    """
    return execute("DELETE FROM web_resources WHERE url = ?", (url,))


# ---------------------------------------------------------------------------
# gold_standard
# ---------------------------------------------------------------------------

def upsert_gold_standard(url: str, gold_text: str) -> None:
    """
    Inserisce o aggiorna il testo di riferimento di un URL.

    Il testo passa dalla normalizzazione perche' arriva quasi sempre da un
    copia-incolla dal browser, che porta con se' caratteri invisibili
    (vedi text_utils). Nel database ne entra una sola versione, pulita.
    """
    execute(
        """
        INSERT INTO gold_standard (url, gold_text)
        VALUES (?, ?)
        ON DUPLICATE KEY UPDATE gold_text = VALUES(gold_text)
        """,
        (url, normalize_gold_text(gold_text)),
    )


def get_gold_standard_entry(url: str) -> Optional[dict]:
    """
    Entry completa del Gold Standard per un URL.

    La JOIN ricompone il formato richiesto da GET /gold_standard: url,
    domain, title e html_text stanno in web_resources, gold_text in
    gold_standard.
    """
    return fetch_one(
        """
        SELECT w.url, w.domain, w.title, w.html_text, g.gold_text
        FROM gold_standard AS g
        JOIN web_resources AS w ON w.url = g.url
        WHERE g.url = ?
        """,
        (url,),
    )


def list_gold_standard_by_domain(domain: str) -> list[dict]:
    """Tutte le entry del Gold Standard di un dominio."""
    return fetch_all(
        """
        SELECT w.url, w.domain, w.title, w.html_text, g.gold_text
        FROM gold_standard AS g
        JOIN web_resources AS w ON w.url = g.url
        WHERE w.domain = ?
        ORDER BY w.url
        """,
        (domain,),
    )


def list_gold_standard_urls(domain: str) -> list[str]:
    """Solo gli URL del Gold Standard di un dominio, senza l'HTML."""
    rows = fetch_all(
        """
        SELECT w.url
        FROM gold_standard AS g
        JOIN web_resources AS w ON w.url = g.url
        WHERE w.domain = ?
        ORDER BY w.url
        """,
        (domain,),
    )
    return [row["url"] for row in rows]


def list_web_resource_urls(domain: str) -> list[str]:
    """
    URL delle risorse web di un dominio, indipendentemente dal gold standard.

    Serve alla Web UI: le pagine caricate dai JSON all'avvio hanno gia' l'HTML
    in web_resources anche quando il gold_text non e' ancora stato scritto.
    Elencarle permette di completarle senza doverle riscaricare, che su alcuni
    domini non sarebbe nemmeno possibile.
    """
    rows = fetch_all(
        "SELECT url FROM web_resources WHERE domain = ? ORDER BY url",
        (domain,),
    )
    return [row["url"] for row in rows]


def gold_standard_exists(url: str) -> bool:
    """Vero se l'URL ha gia' un testo di riferimento."""
    return fetch_one("SELECT 1 AS present FROM gold_standard WHERE url = ?", (url,)) is not None


def delete_gold_standard(url: str) -> int:
    """
    Cancella solo il testo di riferimento.

    La risorsa web resta: e' la differenza fra DELETE /gold_standard e
    DELETE /web_resource richiesta dalla consegna.
    """
    return execute("DELETE FROM gold_standard WHERE url = ?", (url,))


# Dimensione massima, in caratteri, di un singolo invio al database.
#
# MariaDB rifiuta i pacchetti piu' grandi di max_allowed_packet e chiude la
# connessione senza spiegazioni: il client vede solo "Write error: Connection
# reset by peer". Il valore predefinito del server e' 16 MB, e le pagine del
# Gold Standard pesano fino a 1,9 MB di HTML l'una: bastano una decina di
# righe nello stesso invio per superarlo.
#
# Quattro megabyte lasciano un margine ampio anche se il server e' configurato
# al minimo, e il costo di spezzare l'inserimento in piu' invii e' trascurabile
# rispetto al tempo di parsing che segue.
MAX_BYTES_PER_BATCH = 4 * 1024 * 1024


def _a_lotti(righe: list[tuple], limite: int = MAX_BYTES_PER_BATCH):
    """
    Divide le righe in gruppi che stanno sotto il limite di dimensione.

    Il conteggio e' sulla lunghezza dei valori testuali, che e' quello che
    determina la dimensione del pacchetto. Una riga piu' grande del limite
    viene comunque inviata da sola: meglio provarci che scartarla.
    """
    lotto: list[tuple] = []
    peso = 0

    for riga in righe:
        peso_riga = sum(len(v) for v in riga if isinstance(v, str))
        if lotto and peso + peso_riga > limite:
            yield lotto
            lotto, peso = [], 0
        lotto.append(riga)
        peso += peso_riga

    if lotto:
        yield lotto


def bulk_insert_gold_standard(entries: list[dict]) -> int:
    """
    Caricamento iniziale: inserisce risorse web e testi di riferimento.

    Le due tabelle si popolano in due passaggi perche' la foreign key impone
    che la risorsa web esista prima del suo gold standard. Ogni passaggio e'
    diviso in lotti per non superare max_allowed_packet (vedi _a_lotti).
    """
    resources = [
        (e["url"], e["domain"], e.get("title", ""), e.get("html_text", ""))
        for e in entries
    ]
    for lotto in _a_lotti(resources):
        execute_many(
            """
            INSERT INTO web_resources (url, domain, title, html_text)
            VALUES (?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                domain = VALUES(domain),
                title = VALUES(title),
                html_text = VALUES(html_text)
            """,
            lotto,
        )

    golds = [
        (e["url"], normalize_gold_text(e.get("gold_text", "")))
        for e in entries if e.get("gold_text")
    ]
    for lotto in _a_lotti(golds):
        execute_many(
            """
            INSERT INTO gold_standard (url, gold_text)
            VALUES (?, ?)
            ON DUPLICATE KEY UPDATE gold_text = VALUES(gold_text)
            """,
            lotto,
        )

    return len(resources)


def count_web_resources() -> int:
    """Numero totale di risorse web, per capire se il DB e' gia' popolato."""
    row = fetch_one("SELECT COUNT(*) AS n FROM web_resources")
    return int(row["n"]) if row else 0


def all_web_resource_urls() -> set[str]:
    """Tutti gli URL presenti in web_resources, senza filtro sul dominio."""
    return {row["url"] for row in fetch_all("SELECT url FROM web_resources")}


def all_gold_standard_urls() -> set[str]:
    """Tutti gli URL che hanno gia' un testo di riferimento."""
    return {row["url"] for row in fetch_all("SELECT url FROM gold_standard")}


# ---------------------------------------------------------------------------
# parsed_documents, evaluations, judgements
# ---------------------------------------------------------------------------

def save_parsed_document(url: str, parser_name: str, parsed_text: str) -> None:
    """Salva l'output del parser per una risorsa."""
    execute(
        """
        INSERT INTO parsed_documents (url, parser_name, parsed_text)
        VALUES (?, ?, ?)
        ON DUPLICATE KEY UPDATE
            parser_name = VALUES(parser_name),
            parsed_text = VALUES(parsed_text)
        """,
        (url, parser_name, parsed_text),
    )


def save_evaluation(url: str, metric_name: str,
                    precision: Optional[float] = None,
                    recall: Optional[float] = None,
                    f1: Optional[float] = None,
                    score: Optional[float] = None) -> None:
    """
    Salva il risultato di una metrica su una pagina.

    Una metrica nuova non richiede modifiche allo schema: cambia solo il
    valore di metric_name.
    """
    execute(
        """
        INSERT INTO evaluations (url, metric_name, precision_v, recall_v, f1_v, score_v)
        VALUES (?, ?, ?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE
            precision_v = VALUES(precision_v),
            recall_v = VALUES(recall_v),
            f1_v = VALUES(f1_v),
            score_v = VALUES(score_v)
        """,
        (url, metric_name, precision, recall, f1, score),
    )


def save_judgement(url: str, model_name: str, judge_score: int,
                   judge_feedback: str, parse_ok: bool = True) -> None:
    """Salva il giudizio dell'LLM su una pagina, per uno specifico modello."""
    execute(
        """
        INSERT INTO judgements (url, model_name, judge_score, judge_feedback, parse_ok)
        VALUES (?, ?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE
            judge_score = VALUES(judge_score),
            judge_feedback = VALUES(judge_feedback),
            parse_ok = VALUES(parse_ok)
        """,
        (url, model_name, judge_score, judge_feedback, parse_ok),
    )


def get_judgement(url: str, model_name: str) -> Optional[dict]:
    """
    Giudizio gia' calcolato per quella pagina con quel modello, o None.

    Permette a /full_gs_eval di riusare i giudizi del precalcolo invece di
    interrogare l'LLM su ogni entry a ogni chiamata.
    """
    return fetch_one(
        """
        SELECT url, model_name, judge_score, judge_feedback, parse_ok
        FROM judgements
        WHERE url = ? AND model_name = ?
        """,
        (url, model_name),
    )


def urls_without_judgement(model_name: str) -> list[dict]:
    """
    Pagine del Gold Standard non ancora giudicate da quel modello.

    Serve al precalcolo in background: se il backend viene riavviato riprende
    da dove era arrivato invece di rifare tutto.
    """
    return fetch_all(
        """
        SELECT w.url, w.domain, w.html_text, g.gold_text
        FROM gold_standard AS g
        JOIN web_resources AS w ON w.url = g.url
        LEFT JOIN judgements AS j ON j.url = g.url AND j.model_name = ?
        WHERE j.url IS NULL
        ORDER BY w.domain, w.url
        """,
        (model_name,),
    )


# ---------------------------------------------------------------------------
# statistiche aggregate
# ---------------------------------------------------------------------------

def _counts_by_domain(query: str) -> dict[str, int]:
    return {row["domain"]: int(row["n"]) for row in fetch_all(query)}


def database_stats() -> dict[str, Any]:
    """
    Statistiche aggregate per dominio, nel formato di GET /db_stats.

    Legge solo valori gia' calcolati e salvati: nessun parsing e nessuna
    chiamata all'LLM, come richiede la specifica.
    """
    web_resources = _counts_by_domain(
        "SELECT domain, COUNT(*) AS n FROM web_resources GROUP BY domain"
    )
    gold_standard = _counts_by_domain(
        """
        SELECT w.domain AS domain, COUNT(*) AS n
        FROM gold_standard AS g
        JOIN web_resources AS w ON w.url = g.url
        GROUP BY w.domain
        """
    )

    metric_rows = fetch_all(
        """
        SELECT w.domain      AS domain,
               e.metric_name AS metric_name,
               AVG(e.precision_v) AS precision_v,
               AVG(e.recall_v)    AS recall_v,
               AVG(e.f1_v)        AS f1_v,
               AVG(e.score_v)     AS score_v
        FROM evaluations AS e
        JOIN web_resources AS w ON w.url = e.url
        GROUP BY w.domain, e.metric_name
        """
    )

    avg_eval: dict[str, dict[str, dict[str, float]]] = {}
    for row in metric_rows:
        values: dict[str, float] = {}
        for source, target in (("precision_v", "precision"),
                               ("recall_v", "recall"),
                               ("f1_v", "f1"),
                               ("score_v", "score")):
            if row[source] is not None:
                values[target] = round(float(row[source]), 4)
        if values:
            avg_eval.setdefault(row["domain"], {})[row["metric_name"]] = values

    judge_rows = fetch_all(
        """
        SELECT w.domain AS domain,
               AVG(j.judge_score) AS judge_score,
               COUNT(*)           AS judged,
               SUM(j.parse_ok)    AS parsed_ok
        FROM judgements AS j
        JOIN web_resources AS w ON w.url = j.url
        GROUP BY w.domain
        """
    )

    avg_eval_judge = {
        row["domain"]: {
            "judge_score": round(float(row["judge_score"]), 4) if row["judge_score"] is not None else 0.0,
            "judged_entries": int(row["judged"]),
            # Quota di risposte in cui il modello ha rispettato il formato
            # JSON: dice quanto ci si puo' fidare della media qui sopra.
            "valid_json_ratio": round(float(row["parsed_ok"]) / int(row["judged"]), 4)
            if row["judged"] else 0.0,
        }
        for row in judge_rows
    }

    # Ogni dominio presente nel DB compare in tutte le sezioni, anche quando
    # non ha ancora valutazioni: la specifica chiede che le metriche
    # obbligatorie e il judge_score siano sempre riportati.
    for domain in web_resources:
        avg_eval.setdefault(domain, {})
        avg_eval[domain].setdefault(TOKEN_LEVEL, {"precision": 0.0, "recall": 0.0, "f1": 0.0})
        avg_eval_judge.setdefault(domain, {"judge_score": 0.0, "judged_entries": 0,
                                           "valid_json_ratio": 0.0})
        gold_standard.setdefault(domain, 0)

    return {
        "web_resources": web_resources,
        "gold_standard": gold_standard,
        "avg_eval": avg_eval,
        "avg_eval_judge": avg_eval_judge,
    }
