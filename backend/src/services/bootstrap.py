"""
Inizializzazione del sistema all'avvio del backend.

La consegna chiede che dopo "docker compose up --build" il sistema sia
utilizzabile senza nessun passaggio intermedio: il Gold Standard dev'essere
gia' nel database e /db_stats deve poter leggere valutazioni gia' calcolate.
Questo modulo e' lo script di inizializzazione che realizza quel requisito.

Divisione del lavoro fra i due tempi di avvio:

  sincrono, prima che l'API accetti richieste
    connessione al database, caricamento dei JSON del Gold Standard,
    parsing di ogni entry e calcolo delle metriche. Tutto questo lavora
    sull'HTML gia' salvato, quindi non tocca la rete ed e' veloce.

  in background, mentre l'API e' gia' online
    i giudizi dell'LLM. Su CPU una singola valutazione puo' richiedere
    diversi secondi: farla in sincrono significherebbe ritardare l'avvio di
    minuti e rischiare che lo script di test parta prima che il backend
    risponda. Il thread riprende da dove era arrivato a ogni riavvio, quindi
    un riavvio non ricomincia da capo.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Iterable, Optional

from src.parsers.registry import get_parser
from src.services import repository
from src.services.database import init_pool
from src.services.evaluator import token_level_eval
from src.services.judge import OLLAMA_MODEL, evaluate_judge, judge_available

logger = logging.getLogger(__name__)

JUDGE_ON_INIT = os.getenv("JUDGE_ON_INIT", "true").lower() in ("1", "true", "yes")

# Ricaricamento forzato del Gold Standard dai file JSON, anche sulle entry gia'
# presenti nel database. Spento di proposito: durante la costruzione del Gold
# Standard i testi vivono nel database prima di essere esportati, e un riavvio
# che li sovrascrivesse con la versione vecchia dei file cancellerebbe lavoro
# manuale non riproducibile. Si accende quando i file sono la versione buona e
# il database va riallineato:  GS_FORCE_RELOAD=true docker compose up -d
GS_FORCE_RELOAD = os.getenv("GS_FORCE_RELOAD", "false").lower() in ("1", "true", "yes")

# Quanti secondi attendere al massimo che Ollama abbia finito di scaricare il
# modello, prima di rinunciare al precalcolo dei giudizi.
JUDGE_WAIT_SECONDS = int(os.getenv("JUDGE_WAIT_SECONDS", "600"))


def _iter_gold_standard_files(gs_dir: Path) -> Iterable[Path]:
    """File JSON del Gold Standard presenti nella cartella."""
    if not gs_dir.is_dir():
        logger.error("Cartella dei Gold Standard non trovata: %s", gs_dir)
        return []
    return sorted(gs_dir.glob("*_gs.json"))


def _entry_valide(path: Path) -> list[dict]:
    """
    Entry leggibili di un file del Gold Standard.

    Le entry senza url o senza html_text vengono scartate con un avviso: una
    risorsa web senza HTML non serve a niente e farebbe fallire il parsing in
    fase di valutazione.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Salto %s: %s", path.name, exc)
        return []

    if not isinstance(data, list):
        logger.error("Salto %s: il file non contiene una lista di entry", path.name)
        return []

    valide = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if not entry.get("url") or not entry.get("html_text"):
            logger.warning("Salto un'entry di %s priva di url o html_text", path.name)
            continue
        valide.append(entry)

    return valide


def load_gold_standard_files(gs_dir: Path, force: bool = False) -> dict:
    """
    Allinea il database ai file JSON del Gold Standard.

    Il criterio non e' "il database e' vuoto, quindi carico tutto": era quello
    di prima, e aveva un difetto silenzioso. Bastava che il database contenesse
    una riga qualsiasi perche' i file venissero ignorati per sempre, cosi' che
    pagine aggiunte ai JSON non comparissero mai e nessuno se ne accorgesse.

    Il criterio nuovo lavora per differenza:

      * le entry presenti nei file ma assenti dal database vengono inserite,
        sempre, a ogni avvio;
      * le entry gia' presenti nel database NON vengono sovrascritte, a meno
        che non si chieda esplicitamente il ricaricamento con la variabile
        d'ambiente GS_FORCE_RELOAD. Il motivo e' pratico: durante la
        costruzione del Gold Standard i testi si scrivono dalla Web UI e
        vivono nel database prima di essere esportati. Un riavvio che li
        sovrascrivesse con la versione vecchia dei file distruggerebbe ore di
        lavoro manuale, che e' l'unica parte non riproducibile del sistema;
      * se un URL ha gia' la risorsa web ma non ancora il testo di riferimento,
        e il file ce l'ha, quello viene inserito: e' un buco da riempire, non
        un dato da sovrascrivere.

    Returns:
        Riepilogo con inseriti, completati, gia' presenti e non_nei_file.
    """
    presenti = repository.all_web_resource_urls()
    con_gold = repository.all_gold_standard_urls()

    da_inserire: list[dict] = []
    da_completare: list[dict] = []
    gia_presenti = 0
    url_nei_file: set[str] = set()

    for path in _iter_gold_standard_files(gs_dir):
        entry = _entry_valide(path)
        if not entry:
            continue

        url_nei_file.update(e["url"] for e in entry)

        for e in entry:
            if force or e["url"] not in presenti:
                da_inserire.append(e)
            elif e.get("gold_text") and e["url"] not in con_gold:
                da_completare.append(e)
            else:
                gia_presenti += 1

        logger.info("Lette %d entry da %s", len(entry), path.name)

    if da_inserire:
        repository.bulk_insert_gold_standard(da_inserire)
    if da_completare:
        repository.bulk_insert_gold_standard(da_completare)

    # Divergenza nell'altro verso: righe che stanno nel database e non nei
    # file. Non le tocco — potrebbero essere lavoro in corso — ma lo dico,
    # perche' al prossimo avvio su una macchina pulita sparirebbero senza
    # preavviso. E' il momento giusto per ricordarsi di esportare.
    non_nei_file = sorted(presenti - url_nei_file)
    if non_nei_file:
        logger.warning(
            "%d risorse sono nel database ma non nei file di gs_data/: "
            "su una macchina pulita non verrebbero caricate. "
            "Esportale con 'python3 backend/tools/gs.py esporta'. Prima tre: %s",
            len(non_nei_file), ", ".join(non_nei_file[:3]),
        )

    return {
        "inserite": len(da_inserire),
        "completate": len(da_completare),
        "gia_presenti": gia_presenti,
        "non_nei_file": len(non_nei_file),
    }


def precompute_metrics() -> int:
    """
    Esegue il parsing di ogni entry del Gold Standard e salva le metriche.

    Si lavora sempre sull'HTML statico del database: e' quello che chiede la
    consegna per l'evaluation, ed e' anche l'unico modo di avere numeri
    confrontabili nel tempo su siti che cambiano ogni giorno.

    Returns:
        Numero di entry valutate.
    """
    done = 0

    for domain in _domains_in_db():
        for entry in repository.list_gold_standard_by_domain(domain):
            url = entry["url"]
            parser, _ = get_parser(url)
            if parser is None:
                logger.warning("Nessun parser per %s, salto", url)
                continue

            try:
                result = parser(url, html_text=entry["html_text"])
            except Exception as exc:
                logger.error("Parsing fallito su %s: %s", url, exc)
                continue

            parsed_text = result.get("parsed_text", "")
            repository.save_parsed_document(url, parser.name, parsed_text)

            scores = token_level_eval(parsed_text, entry.get("gold_text", ""))
            repository.save_evaluation(
                url,
                repository.TOKEN_LEVEL,
                precision=scores["precision"],
                recall=scores["recall"],
                f1=scores["f1"],
            )
            done += 1

    return done


def _domains_in_db() -> list[str]:
    """Domini effettivamente presenti in web_resources."""
    stats = repository.database_stats()
    return list(stats["web_resources"].keys())


def _wait_for_judge() -> bool:
    """
    Attende che Ollama abbia il modello pronto.

    Al primo avvio il container sta scaricando qualche gigabyte: senza questa
    attesa il precalcolo partirebbe subito e fallirebbe su ogni entry.
    """
    import time

    waited = 0
    while waited < JUDGE_WAIT_SECONDS:
        if judge_available():
            return True
        time.sleep(10)
        waited += 10

    logger.warning("Ollama non pronto dopo %d secondi: salto il precalcolo dei giudizi",
                   JUDGE_WAIT_SECONDS)
    return False


def precompute_judgements() -> None:
    """
    Calcola i giudizi mancanti sul Gold Standard, una entry alla volta.

    Pensata per girare in un thread separato: l'API e' gia' online mentre
    questo lavora. Ogni giudizio viene salvato subito, cosi' /db_stats mostra
    valori via via piu' completi invece di restare vuota fino alla fine.
    """
    if not _wait_for_judge():
        return

    pending = repository.urls_without_judgement(OLLAMA_MODEL)
    if not pending:
        logger.info("Giudizi gia' presenti per tutte le entry del Gold Standard")
        return

    logger.info("Precalcolo dei giudizi su %d entry con il modello %s",
                len(pending), OLLAMA_MODEL)

    for index, row in enumerate(pending, start=1):
        url = row["url"]
        parser, _ = get_parser(url)
        if parser is None:
            continue

        try:
            parsed_text = parser(url, html_text=row["html_text"]).get("parsed_text", "")
        except Exception as exc:
            logger.error("Parsing fallito su %s durante il precalcolo: %s", url, exc)
            continue

        verdict = evaluate_judge(parsed_text, row.get("gold_text", ""))
        repository.save_judgement(
            url,
            verdict["model_name"],
            verdict["judge_score"],
            verdict["judge_feedback"],
            verdict["parse_ok"],
        )

        if index % 5 == 0 or index == len(pending):
            logger.info("Giudizi calcolati: %d/%d", index, len(pending))

    logger.info("Precalcolo dei giudizi completato")


def initialize(gs_dir: Path, force_reload: Optional[bool] = None) -> dict:
    """
    Inizializza il sistema. Chiamata una volta all'avvio del backend.

    Args:
        gs_dir: cartella con i JSON del Gold Standard.
        force_reload: sovrascrive anche le entry gia' nel database. Se None si
                      usa la variabile d'ambiente GS_FORCE_RELOAD.

    Returns:
        Riepilogo di cio' che e' stato fatto, utile nei log di avvio.
    """
    if force_reload is None:
        force_reload = GS_FORCE_RELOAD

    init_pool()

    already_loaded = repository.count_web_resources()

    riepilogo = load_gold_standard_files(gs_dir, force=force_reload)
    logger.info(
        "Gold Standard allineato: %d inserite, %d completate, %d gia' presenti%s",
        riepilogo["inserite"], riepilogo["completate"], riepilogo["gia_presenti"],
        f", {riepilogo['non_nei_file']} solo nel database" if riepilogo["non_nei_file"] else "",
    )

    evaluated = precompute_metrics()
    logger.info("Metriche precalcolate su %d entry", evaluated)

    if JUDGE_ON_INIT:
        thread = threading.Thread(target=precompute_judgements,
                                  name="precompute-judgements",
                                  daemon=True)
        thread.start()

    return {
        "gold_standard_loaded": riepilogo["inserite"] + riepilogo["completate"],
        "already_present": already_loaded,
        "metrics_computed": evaluated,
        "judge_scheduled": JUDGE_ON_INIT,
    }
