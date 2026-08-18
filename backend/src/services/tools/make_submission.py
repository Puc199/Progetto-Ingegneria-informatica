"""
Crea l'archivio di consegna.

La consegna chiede un singolo file zip della cartella del progetto, chiamato
matricola1_matricola2_matricola3_lab_progetto.zip, con dentro la struttura
esatta delle slide e senza file di lavoro.

Zippare a mano da Esplora risorse su Windows e' facile che porti dentro
__pycache__, i file .bak, la cartella .git da decine di megabyte e i risultati
dei benchmark. Questo script fa la stessa cosa in modo ripetibile, elenca cosa
esclude e verifica che nell'archivio ci sia tutto quello che serve.

Uso (dalla root del progetto, quella con docker-compose.yaml):

    python backend/tools/make_submission.py --matricole 1234567 1234568 1234569

    python backend/tools/make_submission.py --matricole 1234567 --dry-run
        elenca i file che finirebbero nell'archivio senza crearlo

Funziona identico su Windows, macOS e Linux: usa solo la libreria standard.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

# Cartelle escluse ovunque si trovino.
EXCLUDE_DIRS = {
    ".git", ".github", "__pycache__", ".venv", "venv", "env",
    ".idea", ".vscode", ".pytest_cache", ".mypy_cache", "node_modules",
}

# File esclusi, per nome esatto o per estensione.
EXCLUDE_NAMES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
    "judge_benchmark_summary.md", "judge_benchmark_details.json",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".bak", ".log", ".tmp", ".swp"}

# File e cartelle che devono esserci: se ne manca uno il progetto non parte
# sulla macchina del docente, ed e' meglio scoprirlo adesso.
REQUIRED = [
    "docker-compose.yaml",
    "domains.json",
    "backend/Dockerfile",
    "backend/requirements.txt",
    "backend/src",
    "frontend/Dockerfile",
    "frontend/requirements.txt",
    "frontend/src/templates",
    "gs_data",
    "mariadb_data",
    "ollama_data",
]

# Presenti nella struttura della consegna ma non bloccanti in fase di test.
RECOMMENDED = ["report.pdf"]


def is_excluded(path: Path, root: Path) -> bool:
    """Vero se il percorso va tenuto fuori dall'archivio."""
    relative = path.relative_to(root)

    if any(part in EXCLUDE_DIRS for part in relative.parts):
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return False


def collect(root: Path) -> tuple[list[Path], list[Path]]:
    """Restituisce (file da includere, file esclusi)."""
    included: list[Path] = []
    excluded: list[Path] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        (excluded if is_excluded(path, root) else included).append(path)

    return included, excluded


def check_required(root: Path) -> list[str]:
    """Elementi obbligatori assenti."""
    return [name for name in REQUIRED if not (root / name).exists()]


def check_gold_standard(root: Path) -> list[str]:
    """
    Avvisa sui Gold Standard incompleti.

    Un file di gold standard con i gold_text vuoti non fa fallire l'avvio, ma
    rende impossibile valutare quel dominio: meglio accorgersene prima di
    consegnare che dopo.
    """
    import json

    warnings: list[str] = []
    gs_dir = root / "gs_data"
    if not gs_dir.is_dir():
        return ["gs_data/ non esiste"]

    files = sorted(gs_dir.glob("*_gs.json"))
    if not files:
        return ["gs_data/ non contiene nessun file *_gs.json"]

    for path in files:
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{path.name}: non leggibile ({exc})")
            continue

        if not isinstance(entries, list):
            warnings.append(f"{path.name}: non contiene una lista")
            continue

        total = len(entries)
        with_gold = sum(1 for e in entries if isinstance(e, dict) and e.get("gold_text"))

        if with_gold < 10:
            warnings.append(
                f"{path.name}: {with_gold} entry con gold_text su {total} "
                "(la consegna ne chiede almeno 10)"
            )

    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea l'archivio di consegna")
    parser.add_argument("--matricole", nargs="+", required=True,
                        help="matricole dei membri del gruppo")
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="cartella del progetto (default: quella corrente)")
    parser.add_argument("--dry-run", action="store_true",
                        help="mostra cosa verrebbe incluso senza creare l'archivio")
    args = parser.parse_args()

    root = args.root.resolve()
    if not (root / "docker-compose.yaml").exists():
        raise SystemExit(f"{root} non sembra la root del progetto: manca docker-compose.yaml.\n"
                         "Lancia lo script dalla cartella che contiene docker-compose.yaml.")

    missing = check_required(root)
    if missing:
        print("MANCANO ELEMENTI OBBLIGATORI:")
        for name in missing:
            print(f"  - {name}")
        raise SystemExit("Archivio non creato.")

    for name in RECOMMENDED:
        if not (root / name).exists():
            print(f"[avviso] manca {name}, previsto dalla struttura della consegna")

    for warning in check_gold_standard(root):
        print(f"[avviso] {warning}")

    included, excluded = collect(root)
    total_mb = sum(p.stat().st_size for p in included) / (1024 * 1024)

    print(f"\nFile da includere: {len(included)}  ({total_mb:.1f} MB non compressi)")
    print(f"File esclusi     : {len(excluded)}")
    if excluded:
        shown = excluded[:8]
        for path in shown:
            print(f"  - {path.relative_to(root)}")
        if len(excluded) > len(shown):
            print(f"  ... e altri {len(excluded) - len(shown)}")

    archive_name = "_".join(args.matricole) + "_lab_progetto.zip"
    archive_path = root.parent / archive_name

    if args.dry_run:
        print(f"\nDry run: l'archivio sarebbe {archive_path}")
        return

    # La cartella del progetto viene messa dentro l'archivio come radice, come
    # richiede la consegna ("lo zip della cartella del vostro progetto").
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in included:
            archive.write(path, arcname=str(Path(root.name) / path.relative_to(root)))

    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print(f"\nCreato {archive_path}  ({size_mb:.1f} MB)")
    print("Ricorda: va consegnata la copia del progetto COME ERA PRIMA di eseguire i test.")


if __name__ == "__main__":
    main()
