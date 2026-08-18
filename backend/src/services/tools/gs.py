#!/usr/bin/env python3
"""
Strumento da riga di comando per costruire e mantenere il Gold Standard.

Sostituisce gli script PowerShell usati durante lo sviluppo: qui la stessa
logica gira identica su Windows, Linux e macOS, e non aggiunge dipendenze
perche' usa solo la libreria standard.

Tutte le operazioni passano dalle API REST del backend, mai dal database:
il livello REST e' quello che la consegna dichiara come interfaccia del
sistema, e usarlo anche dagli strumenti interni significa provarlo ogni volta.

Uso (dalla root del progetto, con lo stack avviato):

    python3 backend/tools/gs.py stato
    python3 backend/tools/gs.py scarica URL [URL ...]
    python3 backend/tools/gs.py aggiungi URL FILE.txt
    python3 backend/tools/gs.py misura URL
    python3 backend/tools/gs.py misura-dominio DOMINIO
    python3 backend/tools/gs.py rimuovi URL [URL ...]
    python3 backend/tools/gs.py togli-da-json FILE.json URL [URL ...]
    python3 backend/tools/gs.py backup
    python3 backend/tools/gs.py esporta [--verifica]

Opzione comune:  --api http://localhost:8003
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "http://localhost:8003"

# Wikimedia chiede uno User-Agent che identifichi l'applicazione e offra un
# contatto: una stringa di browser generica e' uno dei motivi per cui si viene
# limitati piu' facilmente.
USER_AGENT = ("LabIngInf-GoldStandardBuilder/1.0 "
              "(progetto universitario; contatto via Google Classroom)")

MIN_CARATTERI_PAGINA = 5000
MIN_CARATTERI_GOLD = 400

NOMI_FILE = {
    "en.wikipedia.org": "wikipedia_gs.json",
    "www.basketball-reference.com": "basketballreference_gs.json",
    "global.morningstar.com": "globalmorningstar_gs.json",
    "it.tradingview.com": "ittradingview_gs.json",
}


# --------------------------------------------------------------------------- #
# Fondamenta
# --------------------------------------------------------------------------- #

def trova_root() -> Path:
    """Risale da questo file fino alla cartella che contiene docker-compose.yaml."""
    for cartella in [Path(__file__).resolve().parent, Path.cwd().resolve()]:
        for candidata in [cartella, *cartella.parents]:
            if (candidata / "docker-compose.yaml").exists():
                return candidata
    sys.exit("Root del progetto non trovata: lancia il comando dalla cartella del progetto.")


def chiama(percorso: str, metodo: str = "GET", corpo: dict | None = None,
           timeout: int = 900) -> dict:
    """
    Una richiesta alle API del backend.

    Il corpo viaggia sempre come UTF-8 dichiarato: senza dichiararlo, alcuni
    client lo spedirebbero nella codifica di sistema e le lettere accentate
    arriverebbero storpiate nel database.
    """
    dati = None
    intestazioni = {"Accept": "application/json"}
    if corpo is not None:
        dati = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        intestazioni["Content-Type"] = "application/json; charset=utf-8"

    richiesta = urllib.request.Request(API + percorso, data=dati,
                                       headers=intestazioni, method=metodo)
    try:
        with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
            return json.loads(risposta.read().decode("utf-8"))
    except urllib.error.HTTPError as errore:
        testo = errore.read().decode("utf-8", "replace")
        try:
            dettaglio = json.loads(testo).get("detail")
            if isinstance(dettaglio, list):
                dettaglio = "; ".join(d.get("msg", "") for d in dettaglio)
        except json.JSONDecodeError:
            dettaglio = testo[:300]
        sys.exit(f"Il backend ha risposto {errore.code}: {dettaglio}")
    except urllib.error.URLError as errore:
        sys.exit(f"Backend non raggiungibile su {API}: {errore.reason}\n"
                 "Avvia lo stack con 'docker compose up -d' e riprova.")


def q(valore: str) -> str:
    return urllib.parse.quote(valore, safe="")


def domini() -> list[str]:
    return chiama("/domains", timeout=30)["domains"]


# --------------------------------------------------------------------------- #
# scarica
# --------------------------------------------------------------------------- #

def scarica_html(indirizzo: str, tentativi: int, pausa: int) -> str | None:
    """
    Scarica una pagina, riprovando quando il sito limita le richieste.

    Perche' non si passa da Crawl4AI: le pagine dei quattro domini sono
    renderizzate lato server, quindi l'HTML e' gia' completo nella prima
    risposta HTTP. Il parser continua a usare Crawl4AI, che resta la libreria
    richiesta dalla consegna; qui si tratta solo di popolare il Gold Standard,
    e l'HTML grezzo e' anche piu' stabile di quello renderizzato.
    """
    for tentativo in range(1, tentativi + 1):
        richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(richiesta, timeout=60) as risposta:
                return risposta.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as errore:
            if errore.code not in (429, 503):
                print(f"  errore HTTP {errore.code}")
                return None
            if tentativo == tentativi:
                print(f"  {errore.code} anche al tentativo {tentativo}: il sito limita le richieste.")
                return None
            attesa = int(errore.headers.get("Retry-After") or 0) or pausa * (3 ** tentativo)
            print(f"  {errore.code} ricevuto, aspetto {attesa}s e riprovo...")
            time.sleep(attesa)
        except urllib.error.URLError as errore:
            print(f"  connessione fallita: {errore.reason}")
            return None
    return None


def comando_scarica(args) -> None:
    bloccati: set[str] = set()
    ok = falliti = saltati = 0

    for indice, indirizzo in enumerate(args.url, start=1):
        dominio = urllib.parse.urlparse(indirizzo).hostname or ""
        print(f"\n[{indice}/{len(args.url)}] {indirizzo}")

        if dominio in bloccati:
            print(f"  {dominio} ha gia' rifiutato: salto senza insistere.")
            saltati += 1
            continue

        html = scarica_html(indirizzo, args.tentativi, args.pausa)
        if html is None:
            bloccati.add(dominio)
            falliti += 1
            continue

        if len(html) < MIN_CARATTERI_PAGINA:
            print(f"  solo {len(html)} caratteri: pagina di errore o blocco. La salto.")
            falliti += 1
            continue

        print(f"  scaricati {len(html)} caratteri, salvo nel database...")
        esito = chiama("/add_web_resource", "POST", {"url": indirizzo, "html_text": html})
        print(f"  salvato ({esito.get('status')})")
        ok += 1

        if indice < len(args.url):
            time.sleep(args.pausa)

    print(f"\nRiepilogo: {ok} salvate, {falliti} fallite, {saltati} saltate.")
    if bloccati:
        print("Domini che hanno limitato le richieste: " + ", ".join(sorted(bloccati)))
        print("Riprova fra una decina di minuti, solo con le pagine di quei domini.")


# --------------------------------------------------------------------------- #
# aggiungi
# --------------------------------------------------------------------------- #

def comando_aggiungi(args) -> None:
    percorso = Path(args.file)
    if not percorso.exists():
        sys.exit(f"File non trovato: {percorso}")

    testo = percorso.read_text(encoding="utf-8").strip()
    if not testo:
        sys.exit("Il file e' vuoto.")

    print(f"URL   : {args.url}")
    print(f"Testo : {len(testo)} caratteri, da {percorso}")

    # Una soglia bassa quasi sempre significa che sono state copiate poche
    # righe: meglio chiedere conferma che riempire il Gold Standard di entry
    # inutilizzabili.
    if len(testo) < MIN_CARATTERI_GOLD and not args.forza:
        risposta = input("Sono pochi caratteri per un testo informativo. Salvare comunque? (s/N) ")
        if risposta.strip().lower() != "s":
            sys.exit("Annullato.")

    esito = chiama("/add_gold_standard", "POST", {"url": args.url, "gold_text": testo})
    print(f"Salvato ({esito.get('status')}).")

    if not args.zitto:
        misura(args.url)


# --------------------------------------------------------------------------- #
# misura
# --------------------------------------------------------------------------- #

def misura(url: str) -> None:
    """Parsing e metriche di una singola pagina, sull'HTML salvato nel database."""
    parsed = chiama(f"/parse?url={q(url)}&local=true")["parsed_text"]
    gold = chiama(f"/gold_standard?url={q(url)}")["gold_text"]
    voti = chiama("/evaluate", "POST", {"parsed_text": parsed, "gold_text": gold})

    t = voti["token_level_eval"]
    s = voti.get("sequence_eval") or {}
    print(f"  parsed {len(parsed)}  gold {len(gold)}")
    print(f"  P {t['precision']:.3f}  R {t['recall']:.3f}  F1 {t['f1']:.3f}"
          f"   (sequence F1 {s.get('f1', 0):.3f})")


def comando_misura(args) -> None:
    misura(args.url)


def comando_misura_dominio(args) -> None:
    elenco = [args.dominio] if args.dominio else domini()
    for dominio in elenco:
        r = chiama(f"/full_gs_eval?domain={q(dominio)}")
        t = r["token_level_eval"]
        s = r.get("sequence_eval") or {}
        print(f"{dominio:<32} token F1 {t['f1']:.3f}   sequence F1 {s.get('f1', 0):.3f}"
              f"   judge {r['judge_score']:.2f}   entry {r['evaluated_entries']}")


# --------------------------------------------------------------------------- #
# stato
# --------------------------------------------------------------------------- #

def comando_stato(args) -> None:
    print(f"{'dominio':<32}{'scaricate':>11}{'con testo':>11}{'mancano':>9}")
    print("-" * 63)
    for dominio in domini():
        risorse = chiama(f"/web_resource_urls?domain={q(dominio)}")["web_resource_urls"]
        gold = chiama(f"/gold_standard_urls?domain={q(dominio)}")["gold_standard_urls"]
        print(f"{dominio:<32}{len(risorse):>11}{len(gold):>11}{max(0, 10 - len(gold)):>9}")

    if args.mancanti:
        for dominio in domini():
            risorse = chiama(f"/web_resource_urls?domain={q(dominio)}")["web_resource_urls"]
            gold = set(chiama(f"/gold_standard_urls?domain={q(dominio)}")["gold_standard_urls"])
            attesa = [u for u in risorse if u not in gold]
            if attesa:
                print(f"\n{dominio}, in attesa di gold_text:")
                for u in attesa:
                    print(f"  {u}")


# --------------------------------------------------------------------------- #
# rimuovi
# --------------------------------------------------------------------------- #

def comando_rimuovi(args) -> None:
    for url in args.url:
        esito = chiama("/web_resource", "DELETE", {"url": url})
        print(f"{esito.get('status'):<6} {url}")
    print("\nIl gold_standard associato e' stato cancellato a cascata (ON DELETE CASCADE).")
    print("Ricorda di riesportare i JSON, altrimenti al prossimo caricamento tornano.")


def comando_togli_da_json(args) -> None:
    """
    Toglie delle entry da un file del Gold Standard.

    Serve quando si cambiano le pagine di un dominio: il database si ripopola
    dai JSON a ogni avvio su macchina pulita, quindi finche' una entry resta
    nel file continua a tornare.
    """
    percorso = Path(args.file)
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    prima = len(dati)

    da_togliere = set(args.url)
    rimaste = [e for e in dati if e.get("url") not in da_togliere]
    tolte = {e["url"] for e in dati if e.get("url") in da_togliere}

    for url in args.url:
        print(("tolta   " if url in tolte else "assente ") + url)

    percorso.write_text(json.dumps(rimaste, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\n{percorso.name}: da {prima} a {len(rimaste)} entry.")


# --------------------------------------------------------------------------- #
# backup
# --------------------------------------------------------------------------- #

def comando_backup(args) -> None:
    """
    Copia di sicurezza del database, fuori dalla cartella del progetto.

    I gold_text vivono in un volume Docker: un 'docker compose down -v' li
    cancella senza chiedere conferma, e con loro ore di lavoro manuale. Il file
    finisce in ../backup_progetto/ cosi' non entra nello zip di consegna e
    sopravvive anche se la cartella del progetto viene ricreata.
    """
    root = trova_root()
    cartella = root.parent / "backup_progetto"
    cartella.mkdir(exist_ok=True)

    stampo = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    destinazione = cartella / f"parsing_db_{stampo}.sql"

    comando = ["docker", "exec", "lab_mariadb", "mariadb-dump",
               "-u", "lab_user", "-plab_password", "--single-transaction", "parsing_db"]
    try:
        esito = subprocess.run(comando, capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as errore:
        sys.exit(f"Copia fallita: {errore}. Il container lab_mariadb e' avviato?")

    destinazione.write_bytes(esito.stdout)
    mb = destinazione.stat().st_size / (1024 * 1024)
    if mb < 0.1:
        sys.exit(f"Il file e' quasi vuoto ({mb:.1f} MB): qualcosa non ha funzionato.")

    print(f"Salvato: {destinazione}  ({mb:.1f} MB)")


# --------------------------------------------------------------------------- #
# esporta
# --------------------------------------------------------------------------- #

def comando_esporta(args) -> None:
    """
    Riscrive i JSON di gs_data/ a partire dal database.

    I gold_text scritti a mano vivono in MariaDB, ma la consegna chiede che i
    file JSON stiano dentro il progetto, ed e' da quelli che il sistema si
    ripopola al primo avvio su una macchina pulita.
    """
    root = trova_root()
    cartella = root / "gs_data"
    cartella.mkdir(exist_ok=True)

    print(f"Progetto : {root}")
    print(f"Cartella : {cartella}\n")

    problemi: list[str] = []
    totale = 0

    for dominio in domini():
        print(dominio)
        entry = chiama(f"/full_gold_standard?domain={q(dominio)}")["gold_standard"]
        con_gold = sum(1 for e in entry if (e.get("gold_text") or "").strip())
        sospetti = sum(1 for e in entry if len(e.get("html_text") or "") < 1000)

        print(f"  entry: {len(entry)}   con gold_text: {con_gold}   html sospetti: {sospetti}")

        if len(entry) < 10:
            problemi.append(f"{dominio}: solo {len(entry)} entry (ne servono 10)")
        if con_gold < len(entry):
            problemi.append(f"{dominio}: {len(entry) - con_gold} entry senza gold_text")
        if sospetti:
            problemi.append(f"{dominio}: {sospetti} entry con html_text sospetto")

        if args.verifica:
            continue

        nome = NOMI_FILE.get(dominio) or re.sub(r"[^a-z0-9]", "", dominio.lower()) + "_gs.json"
        destinazione = cartella / nome

        # Un file con meno gold_text di quello gia' su disco quasi sempre
        # significa che il database non contiene ancora tutto: sovrascriverlo
        # peggiorerebbe la situazione invece di salvarla.
        if destinazione.exists():
            try:
                esistenti = json.loads(destinazione.read_text(encoding="utf-8"))
                gia_presenti = sum(1 for e in esistenti if (e.get("gold_text") or "").strip())
                if gia_presenti > con_gold:
                    print(f"  ATTENZIONE: il file su disco ha {gia_presenti} gold_text, "
                          f"il database solo {con_gold}. Non sovrascrivo.")
                    problemi.append(f"{dominio}: file NON sovrascritto")
                    continue
            except (OSError, json.JSONDecodeError):
                pass

        pulite = [{campo: e.get(campo, "") for campo in
                   ("url", "domain", "title", "html_text", "gold_text")} for e in entry]
        destinazione.write_text(json.dumps(pulite, ensure_ascii=False, indent=2),
                                encoding="utf-8")

        mb = destinazione.stat().st_size / (1024 * 1024)
        print(f"  scritto {nome} ({mb:.1f} MB)")
        totale += len(entry)

    print()
    if problemi:
        print("Da controllare:")
        for p in problemi:
            print(f"  - {p}")
    else:
        print("Tutti i domini hanno 10 entry complete.")

    if not args.verifica:
        print(f"\nEsportate {totale} entry in totale.")


# --------------------------------------------------------------------------- #

def main() -> None:
    global API

    genitore = argparse.ArgumentParser(add_help=False)
    genitore.add_argument("--api", default=API, help="indirizzo del backend")

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sotto = parser.add_subparsers(dest="comando", required=True)

    p = sotto.add_parser("scarica", parents=[genitore], help="scarica pagine e le salva nel database")
    p.add_argument("url", nargs="+")
    p.add_argument("--pausa", type=int, default=6, help="secondi fra una pagina e l'altra")
    p.add_argument("--tentativi", type=int, default=3)
    p.set_defaults(funzione=comando_scarica)

    p = sotto.add_parser("aggiungi", parents=[genitore], help="salva un gold_text da file")
    p.add_argument("url")
    p.add_argument("file")
    p.add_argument("--forza", action="store_true", help="non chiedere conferma sui testi corti")
    p.add_argument("--zitto", action="store_true", help="non misurare dopo il salvataggio")
    p.set_defaults(funzione=comando_aggiungi)

    p = sotto.add_parser("misura", parents=[genitore], help="metriche di una singola pagina")
    p.add_argument("url")
    p.set_defaults(funzione=comando_misura)

    p = sotto.add_parser("misura-dominio", parents=[genitore], help="metriche aggregate")
    p.add_argument("dominio", nargs="?")
    p.set_defaults(funzione=comando_misura_dominio)

    p = sotto.add_parser("stato", parents=[genitore], help="quante entry per dominio")
    p.add_argument("--mancanti", action="store_true", help="elenca le pagine senza gold_text")
    p.set_defaults(funzione=comando_stato)

    p = sotto.add_parser("rimuovi", parents=[genitore], help="cancella risorse dal database")
    p.add_argument("url", nargs="+")
    p.set_defaults(funzione=comando_rimuovi)

    p = sotto.add_parser("togli-da-json", parents=[genitore], help="toglie entry da un file di gs_data")
    p.add_argument("file")
    p.add_argument("url", nargs="+")
    p.set_defaults(funzione=comando_togli_da_json)

    p = sotto.add_parser("backup", parents=[genitore], help="copia di sicurezza del database")
    p.set_defaults(funzione=comando_backup)

    p = sotto.add_parser("esporta", parents=[genitore], help="riscrive i JSON di gs_data/")
    p.add_argument("--verifica", action="store_true", help="controlla soltanto, non scrive")
    p.set_defaults(funzione=comando_esporta)

    args = parser.parse_args()
    API = args.api.rstrip("/")
    args.funzione(args)


if __name__ == "__main__":
    main()
