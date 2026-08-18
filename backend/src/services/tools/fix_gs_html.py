"""
Rigenera il campo html_text di una o piu' entry del Gold Standard.

Serve quando l'HTML salvato non corrisponde all'URL dell'entry (tipico errore
di copia-incolla in fase di costruzione del GS). Il gold_text NON viene mai
toccato: e' il riferimento costruito a mano e resta quello.

Uso (dalla cartella backend/):

    python tools/fix_gs_html.py --check
        elenca le entry e segnala quelle incoerenti, senza modificare nulla

    python tools/fix_gs_html.py --url https://www.basketball-reference.com/players/d/duncati01.html
        riscarica quella pagina e aggiorna html_text e title

    python tools/fix_gs_html.py --all-broken
        aggiorna tutte le entry segnalate come incoerenti

    python tools/fix_gs_html.py --url ... --dry-run
        mostra cosa farebbe senza scrivere

Prima di scrivere viene sempre creata una copia di sicurezza .bak
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[1]      # cartella backend/
sys.path.insert(0, str(BASE_DIR))

from bs4 import BeautifulSoup                                    # noqa: E402

from src.parsers.base_parser import fetch_html, fetch_html_crawl4ai   # noqa: E402
from src.parsers.registry import get_parser                      # noqa: E402


def resolve_gs(name: str = "basketballreference_gs.json") -> Path:
    for candidate in (BASE_DIR / "gsdata" / name, BASE_DIR.parent / "gsdata" / name):
        if candidate.exists():
            return candidate
    return BASE_DIR / "gsdata" / name


def html_title(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    return soup.title.get_text(strip=True) if soup.title else ""


def slug(url: str) -> str:
    """Ultimo segmento dell'URL senza estensione, es. 'duncati01'."""
    return Path(urlparse(url).path).stem.lower()


def looks_broken(entry: dict) -> tuple[bool, str]:
    """
    Euristica: il titolo dentro html_text dovrebbe avere qualche parola in
    comune con l'URL o con il title dell'entry. Non e' infallibile, ma
    intercetta bene i duplicati da copia-incolla.
    """
    html = entry.get("html_text") or ""
    if not html.strip():
        return True, "html_text vuoto"

    title = html_title(html)
    if not title:
        return True, "html_text senza tag <title>"

    words = {w for w in title.lower().replace(",", " ").split() if len(w) > 3}
    target = slug(entry.get("url") or "")
    if any(w[:5] in target for w in words):
        return False, title
    entry_title = (entry.get("title") or "").lower()
    if entry_title and any(w in entry_title for w in words):
        return False, title
    return True, f"titolo incoerente: {title}"


def load(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data, data.get("gold_standard", [])
    return None, data


def save(path: Path, container, entries) -> None:
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    payload = container if container is not None else entries
    if container is not None:
        container["gold_standard"] = entries
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nScritto {path}\nBackup in {backup}")


def refresh(entry: dict, plain: bool = False) -> bool:
    url = entry.get("url") or ""
    modo = "HTTP semplice" if plain else "Crawl4AI (browser)"
    print(f"  scarico {url}  [{modo}] ...")
    try:
        html = fetch_html(url) if plain else fetch_html_crawl4ai(url)
    except Exception as exc:
        print(f"  ERRORE nel download: {exc}")
        return False
    if not html or not html.strip():
        print("  ERRORE: HTML vuoto")
        return False

    entry["html_text"] = html

    parser, _ = get_parser(url)
    if parser is not None:
        try:
            entry["title"] = parser(url, html_text=html).get("title") or entry.get("title")
        except Exception:
            pass

    print(f"  ok: {len(html)} caratteri, title={html_title(html)!r}")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gs", default=None)
    ap.add_argument("--url", action="append", default=[], help="ripetibile")
    ap.add_argument("--all-broken", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--plain", action="store_true",
                    help="scarica con HTTP semplice invece che con Crawl4AI: "
                         "produce l'HTML servito dal server, senza JS, "
                         "coerente con il resto del Gold Standard")
    args = ap.parse_args()

    path = Path(args.gs) if args.gs else resolve_gs()
    if not path.exists():
        sys.exit(f"File GS non trovato: {path}")
    print(f"Gold Standard: {path}\n")

    container, entries = load(path)

    broken = []
    for i, entry in enumerate(entries):
        bad, info = looks_broken(entry)
        flag = "!! " if bad else "   "
        print(f"{flag}[{i}] {entry.get('url')}")
        print(f"      html={len(entry.get('html_text') or ''):>9} car   "
              f"gold={len(entry.get('gold_text') or ''):>7} car   {info}")
        if bad:
            broken.append(entry)

    if args.check or (not args.url and not args.all_broken):
        if broken:
            print(f"\n{len(broken)} entry da rigenerare. "
                  f"Rilancia con --all-broken (oppure --url <URL>).")
        else:
            print("\nNessuna incoerenza rilevata.")
        return

    targets = [e for e in entries if e.get("url") in args.url] if args.url else broken
    if not targets:
        sys.exit("Nessuna entry corrispondente.")

    print(f"\nDa aggiornare: {len(targets)}")
    if args.dry_run:
        for entry in targets:
            print(f"  (dry-run) {entry.get('url')}")
        return

    changed = sum(1 for entry in targets if refresh(entry, plain=args.plain))
    if changed:
        save(path, container, entries)
    else:
        print("\nNessuna modifica: file lasciato invariato.")


if __name__ == "__main__":
    main()