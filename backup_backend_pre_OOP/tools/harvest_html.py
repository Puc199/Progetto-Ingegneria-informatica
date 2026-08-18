"""
Scarica l'HTML grezzo di una lista di URL e lo salva nel formato Gold Standard,
con il campo gold_text lasciato vuoto.

Serve a due cose:
  1. dare al parser di un dominio nuovo del materiale reale su cui essere
     scritto e misurato, senza dover prima costruire il gold standard a mano;
  2. precaricare html_text e title delle entry che poi verranno completate
     dalla pagina Gold Standard Builder della Web UI.

Il gold_text NON viene mai inventato: resta "" e va compilato a mano, perche'
un gold standard derivato dall'output del parser non misurerebbe piu' nulla.

Uso (dalla cartella backend/):

    python tools/harvest_html.py --urls tools/urls_morningstar.txt
        scarica gli URL elencati e scrive gs_data/<dominio>_gs.json

    python tools/harvest_html.py --urls tools/urls_tradingview.txt --merge
        aggiunge le entry nuove a un file GS esistente, saltando i duplicati

    python tools/harvest_html.py --urls ... --dry-run
        scarica e stampa un riepilogo senza scrivere nulla

    python tools/harvest_html.py --from-dir tools/html_morningstar
        NON scarica nulla: costruisce le entry da pagine gia' salvate a mano
        dal browser. Serve per i domini protetti da anti-bot, dove il
        download automatico riceve solo una pagina di errore. L'URL di ogni
        file viene letto dal suo tag <link rel="canonical"> o
        <meta property="og:url">, che i browser salvano insieme alla pagina.

        Due modi di salvare, con esiti diversi:

          Ctrl+S -> "Pagina web, solo HTML"
            salva l'HTML che il server ha mandato in rete. Va bene per le
            pagine renderizzate lato server (es. gli articoli editoriali).

          DevTools -> Elements -> tasto destro su <html> -> Copy outerHTML,
          poi incolla in un file .html
            salva il DOM com'e' in quel momento, quindi DOPO che il
            JavaScript ha inserito i contenuti. Serve per le pagine che
            arrivano vuote e si riempiono dopo il caricamento: con Ctrl+S
            si otterrebbe solo il guscio con navigazione e footer.

Il file di URL e' un testo con un URL per riga; righe vuote e righe che
iniziano con # vengono ignorate.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[1]      # cartella backend/
sys.path.insert(0, str(BASE_DIR))

from bs4 import BeautifulSoup                                        # noqa: E402

# base_parser importa crawl4ai a livello di modulo. L'import resta dentro
# download() perche' la modalita' --from-dir non tocca la rete e deve
# funzionare anche dove crawl4ai non e' installato.


# Minimo numero di caratteri sotto il quale l'HTML e' quasi certamente
# una pagina di errore, un blocco anti-bot o un guscio vuoto da riempire in JS.
MIN_HTML_CHARS = 5_000


def read_urls(path: Path) -> list[str]:
    """Legge il file di URL, ignorando righe vuote e commenti."""
    if not path.exists():
        raise SystemExit(f"File di URL non trovato: {path}")

    urls: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line in urls:
            print(f"  [dup] URL ripetuto nel file, lo salto: {line}")
            continue
        urls.append(line)

    if not urls:
        raise SystemExit(f"Nessun URL utile in {path}")
    return urls


def domain_of(url: str) -> str:
    """Host dell'URL, in minuscolo, cosi' come finira' in domains.json."""
    return (urlparse(url).hostname or "").lower()


def gs_filename(domain: str) -> str:
    """
    Nome del file GS per un dominio, con la stessa convenzione gia' usata da
    server.domain_to_gs_filename(): host senza www, senza TLD, senza separatori.

    global.morningstar.com -> globalmorningstar_gs.json
    it.tradingview.com     -> ittradingview_gs.json
    """
    base = domain[4:] if domain.startswith("www.") else domain
    for suffix in (".com", ".org", ".it", ".net", ".edu"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    for separator in (".", "-", "_"):
        base = base.replace(separator, "")
    return f"{base}_gs.json"


def page_title(html: str) -> str:
    """Titolo dichiarato dalla pagina, come fa extract_page_title()."""
    soup = BeautifulSoup(html or "", "html.parser")
    return soup.title.get_text(strip=True) if soup.title else ""


def download(url: str) -> tuple[str, str]:
    """
    Scarica una pagina. Prima Crawl4AI (esegue il JS, indispensabile sui siti
    che costruiscono il contenuto lato client), poi il fallback HTTP semplice.

    Restituisce (html, sorgente) dove sorgente e' "crawl4ai", "http" o "".
    """
    from src.parsers.base_parser import fetch_html, fetch_html_crawl4ai

    try:
        html = fetch_html_crawl4ai(url)
        if html and len(html) >= MIN_HTML_CHARS:
            return html, "crawl4ai"
        print(f"  [warn] Crawl4AI ha restituito {len(html or '')} caratteri, riprovo via HTTP")
    except Exception as exc:
        print(f"  [warn] Crawl4AI fallito ({exc}), riprovo via HTTP")

    try:
        html = fetch_html(url)
        return (html, "http") if html else ("", "")
    except Exception as exc:
        print(f"  [err ] anche il fetch HTTP e' fallito: {exc}")
        return "", ""


def build_entry(url: str, html: str) -> dict:
    """Entry nel formato del Gold Standard, con gold_text da compilare a mano."""
    return {
        "url": url,
        "domain": domain_of(url),
        "title": page_title(html),
        "html_text": html,
        "gold_text": "",
    }


def resolve_gs_dir() -> Path:
    """
    Cartella dei Gold Standard: gs_data/ se esiste, altrimenti gsdata/ per
    compatibilita' con la struttura dell'esonero.
    """
    for name in ("gs_data", "gsdata"):
        for candidate in (BASE_DIR / name, BASE_DIR.parent / name):
            if candidate.is_dir():
                return candidate
    return BASE_DIR.parent / "gs_data"


def load_existing(path: Path) -> list[dict]:
    """Entry gia' presenti nel file GS, lista vuota se il file manca o e' vuoto."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise SystemExit(f"{path.name} esiste ma non e' un JSON valido: controllalo prima di procedere")
    if not isinstance(data, list):
        raise SystemExit(f"{path.name} deve contenere una lista di entry")
    return data


def canonical_url(html: str) -> str:
    """
    URL dichiarato dalla pagina stessa.

    Quando si salva una pagina dal browser il percorso del file non dice piu'
    da dove veniva: l'unica fonte affidabile e' quello che la pagina dichiara
    di se', cioe' il link canonico o l'URL Open Graph.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        return canonical["href"].strip()

    og_url = soup.find("meta", attrs={"property": "og:url"})
    if og_url and og_url.get("content"):
        return og_url["content"].strip()

    return ""


def collect_from_dir(directory: Path) -> list[tuple[str, str]]:
    """
    Legge le pagine salvate a mano in una cartella.

    Restituisce una lista di (url, html). I file senza URL dichiarato vengono
    segnalati e saltati: senza URL l'entry non e' agganciabile al Gold Standard.
    """
    if not directory.is_dir():
        raise SystemExit(f"Cartella non trovata: {directory}")

    files = sorted(p for p in directory.iterdir()
                   if p.suffix.lower() in (".html", ".htm") and p.is_file())
    if not files:
        raise SystemExit(f"Nessun file .html in {directory}")

    collected: list[tuple[str, str]] = []
    for path in files:
        html = path.read_text(encoding="utf-8", errors="replace")
        url = canonical_url(html)

        if not url:
            print(f"  [err ] {path.name}: nessun <link rel=canonical> ne' og:url, lo salto. "
                  "Aggiungi a mano il tag oppure rinomina il file e usa --urls.")
            continue
        if len(html) < MIN_HTML_CHARS:
            print(f"  [err ] {path.name}: solo {len(html)} caratteri, sembra una pagina di errore")
            continue

        print(f"  [ok  ] {path.name}: {len(html):>9,} caratteri -> {url}")
        collected.append((url, html))

    return collected


def main() -> None:
    parser = argparse.ArgumentParser(description="Harvest dell'HTML grezzo per il Gold Standard")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--urls", type=Path,
                        help="file di testo con un URL per riga")
    source.add_argument("--from-dir", type=Path, dest="from_dir",
                        help="cartella con pagine .html salvate a mano dal browser")
    parser.add_argument("--merge", action="store_true",
                        help="aggiunge al file GS esistente invece di sovrascriverlo")
    parser.add_argument("--dry-run", action="store_true",
                        help="scarica e riepiloga senza scrivere su disco")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="secondi di pausa fra un download e l'altro (default 2.0)")
    args = parser.parse_args()

    # Le pagine salvate a mano hanno gia' l'HTML: si salta tutta la parte di rete.
    if args.from_dir:
        print(f"Leggo le pagine salvate in {args.from_dir}\n")
        collected = collect_from_dir(args.from_dir)
        if not collected:
            raise SystemExit("Nessuna pagina utilizzabile.")
        urls = [url for url, _ in collected]
        preloaded: dict[str, str] = dict(collected)
    else:
        urls = read_urls(args.urls)
        preloaded = {}

    domains = {domain_of(u) for u in urls}
    if len(domains) != 1:
        raise SystemExit(f"Il file contiene URL di domini diversi ({', '.join(sorted(domains))}). "
                         "Usa un file per dominio, cosi' ogni GS resta separato.")
    domain = domains.pop()

    gs_path = resolve_gs_dir() / gs_filename(domain)
    existing = load_existing(gs_path) if args.merge else []
    already = {entry.get("url") for entry in existing}

    print(f"Dominio   : {domain}")
    print(f"File GS   : {gs_path}")
    print(f"URL da fare: {len(urls)}  (gia' presenti: {len(already)})\n")

    entries: list[dict] = list(existing)
    ok = skipped = failed = 0

    for index, url in enumerate(urls, start=1):
        if url in already:
            print(f"[{index}/{len(urls)}] gia' presente, salto: {url}")
            skipped += 1
            continue

        print(f"[{index}/{len(urls)}] {url}")
        if url in preloaded:
            html, source = preloaded[url], "file locale"
        else:
            html, source = download(url)

        if not html:
            failed += 1
            continue
        if len(html) < MIN_HTML_CHARS:
            print(f"  [err ] solo {len(html)} caratteri: pagina di errore o blocco anti-bot, la scarto")
            failed += 1
            continue

        entry = build_entry(url, html)
        entries.append(entry)
        ok += 1
        print(f"  [ok  ] {len(html):>9,} caratteri via {source} — titolo: {entry['title'][:70]}")

        # Pausa solo fra due richieste di rete: sui file locali non serve.
        if index < len(urls) and not preloaded:
            time.sleep(args.delay)

    print(f"\nRiepilogo: {ok} scaricate, {skipped} saltate, {failed} fallite. Totale nel GS: {len(entries)}")

    if args.dry_run:
        print("Dry run: non ho scritto nulla.")
        return
    if ok == 0:
        print("Nessuna pagina nuova scaricata: non tocco il file.")
        return

    gs_path.parent.mkdir(parents=True, exist_ok=True)
    gs_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scritto {gs_path}")
    print("Il campo gold_text e' vuoto in tutte le entry nuove: va compilato a mano.")


if __name__ == "__main__":
    main()
