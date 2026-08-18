"""
Confronto fra i modelli candidati per il ruolo di judge.

La consegna chiede di provare tutti e cinque i modelli ammessi e di motivare
nel report la scelta di quello definitivo. Questo script produce i numeri su
cui basare quella scelta, invece di deciderla a intuito.

Per ogni modello e per ogni pagina del Gold Standard misura:

  judge_score        il voto dato
  valid_json         se la risposta rispettava il formato richiesto
  secondi            quanto ci ha messo (su CPU e' un criterio vero)
  f1                 il token_level_eval della stessa pagina, come termine
                     di paragone indipendente

L'ultima colonna e' la piu' interessante. Un judge utile deve essere
d'accordo con la metrica quando la metrica e' affidabile: se un modello da'
5 a una pagina con F1 di 0.4, non sta giudicando, sta tirando a indovinare.
Lo script calcola la correlazione di rango fra judge_score e F1 per dare a
quell'intuizione un numero.

Uso (dalla cartella backend/, con lo stack gia' avviato):

    python tools/benchmark_judge.py
        prova tutti e cinque i modelli su 3 pagine per dominio

    python tools/benchmark_judge.py --models llama3.2:3b phi4-mini --per-domain 5
        limita il confronto a due modelli, su 5 pagine per dominio

    python tools/benchmark_judge.py --pull
        scarica i modelli mancanti prima di iniziare (richiede tempo e spazio)

    python tools/benchmark_judge.py --ollama-url http://localhost:11434
        indirizzo di Ollama. Il default e' il nome del servizio Docker
        ('http://ollama:11434'), che si risolve solo dentro la rete dei
        container: eseguendo lo script dall'host serve questo parametro,
        oppure si lancia lo script dentro il container con docker exec.

Produce due file, come nell'esercizio della lezione su Ollama:
    judge_benchmark_summary.md    una riga per modello
    judge_benchmark_details.json  ogni singola risposta, per rileggerle
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[1]      # cartella backend/
sys.path.insert(0, str(BASE_DIR))

import requests                                                      # noqa: E402

from src.parsers.registry import get_parser                          # noqa: E402
from src.services.evaluator import token_level_eval                  # noqa: E402

# I cinque modelli ammessi dalla consegna.
CANDIDATE_MODELS = [
    "gemma4:e2b",
    "llama3.2:3b",
    "phi4-mini",
    "qwen3:4b",
    "ministral-3:3b",
]

# Stesso default di src/services/judge.py: il nome del servizio Docker.
# Da host non si risolve, quindi esiste --ollama-url per sovrascriverlo.
DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")

# Valorizzato in main() dopo aver letto gli argomenti.
OLLAMA_URL = DEFAULT_OLLAMA_URL


def resolve_gs_dir() -> Path:
    """Cartella dei Gold Standard, cercata accanto a backend/ e nella root."""
    for name in ("gs_data", "gsdata"):
        for candidate in (BASE_DIR / name, BASE_DIR.parent / name):
            if candidate.is_dir():
                return candidate
    raise SystemExit("Cartella gs_data/ non trovata")


def load_samples(per_domain: int) -> list[dict]:
    """
    Prende alcune pagine per dominio, saltando quelle senza gold_text.

    Si campiona a intervalli regolari invece di prendere le prime N: le prime
    entry di un file tendono a essere le pagine piu' simili fra loro, e un
    campione poco vario non distingue i modelli.
    """
    samples: list[dict] = []

    for path in sorted(resolve_gs_dir().glob("*_gs.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        usable = [e for e in data
                  if isinstance(e, dict) and e.get("gold_text") and e.get("html_text")]
        if not usable:
            print(f"  [skip] {path.name}: nessuna entry con gold_text")
            continue

        step = max(1, len(usable) // per_domain)
        samples.extend(usable[::step][:per_domain])

    return samples


def prepare(samples: list[dict]) -> list[dict]:
    """Esegue il parsing una volta sola: i modelli devono vedere lo stesso input."""
    prepared: list[dict] = []

    for entry in samples:
        parser, _ = get_parser(entry["url"])
        if parser is None:
            continue

        try:
            parsed_text = parser(entry["url"], html_text=entry["html_text"]).get("parsed_text", "")
        except Exception as exc:
            print(f"  [skip] parsing fallito su {entry['url']}: {exc}")
            continue

        scores = token_level_eval(parsed_text, entry["gold_text"])
        prepared.append({
            "url": entry["url"],
            "domain": entry.get("domain", ""),
            "parsed_text": parsed_text,
            "gold_text": entry["gold_text"],
            "f1": scores["f1"],
        })

    return prepared


def installed_models() -> set[str]:
    """Modelli gia' presenti nel container Ollama."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        response.raise_for_status()
        return {m.get("name", "") for m in response.json().get("models", [])}
    except Exception as exc:
        raise SystemExit(f"Ollama non raggiungibile su {OLLAMA_URL}: {exc}")


def pull_model(model: str) -> bool:
    """Scarica un modello. Puo' richiedere parecchi minuti."""
    print(f"  scarico {model}...")
    try:
        response = requests.post(f"{OLLAMA_URL}/api/pull",
                                 json={"model": model, "stream": False},
                                 timeout=3600)
        response.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [err ] impossibile scaricare {model}: {exc}")
        return False


def spearman(xs: list[float], ys: list[float]) -> Optional[float]:
    """
    Correlazione di rango fra due serie.

    Si usa il rango e non i valori grezzi perche' judge_score e' una scala
    ordinale da 1 a 5: interessa se i due criteri ordinano le pagine allo
    stesso modo, non se i numeri coincidono.
    """
    n = len(xs)
    if n < 3:
        return None

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: values[i])
        result = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2 + 1
            for k in range(i, j + 1):
                result[order[k]] = average
            i = j + 1
        return result

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return round(num / den, 3) if den else None


def run_model(model: str, cases: list[dict]) -> list[dict]:
    """Fa giudicare a un modello tutti i casi preparati."""
    # Importato qui e non in cima perche' evaluate_judge legge il modello di
    # default dall'ambiente: il modulo va caricato dopo che lo abbiamo fissato.
    from src.services.judge import evaluate_judge

    results: list[dict] = []
    for index, case in enumerate(cases, start=1):
        started = time.monotonic()
        verdict = evaluate_judge(case["parsed_text"], case["gold_text"], model_name=model)
        elapsed = time.monotonic() - started

        results.append({
            "url": case["url"],
            "domain": case["domain"],
            "f1": round(case["f1"], 4),
            "judge_score": verdict["judge_score"],
            "valid_json": verdict["parse_ok"],
            "seconds": round(elapsed, 1),
            "feedback": verdict["judge_feedback"],
        })
        print(f"    [{index}/{len(cases)}] score={verdict['judge_score']} "
              f"json={'ok' if verdict['parse_ok'] else 'KO'} "
              f"{elapsed:5.1f}s  f1={case['f1']:.3f}  {case['url'][-45:]}")

    return results


def summarize(results_by_model: dict[str, list[dict]]) -> str:
    """Tabella riassuntiva in Markdown, una riga per modello."""
    lines = [
        "# Confronto dei modelli candidati come judge",
        "",
        "| Modello | Voto medio | JSON validi | Secondi medi | Correlazione con F1 |",
        "|---|---|---|---|---|",
    ]

    for model, rows in results_by_model.items():
        if not rows:
            lines.append(f"| {model} | — | — | — | non disponibile |")
            continue

        n = len(rows)
        avg_score = sum(r["judge_score"] for r in rows) / n
        valid = sum(1 for r in rows if r["valid_json"]) / n
        avg_time = sum(r["seconds"] for r in rows) / n
        rho = spearman([r["f1"] for r in rows], [float(r["judge_score"]) for r in rows])

        lines.append(
            f"| {model} | {avg_score:.2f} | {valid:.0%} | {avg_time:.1f} | "
            f"{rho if rho is not None else 'campione troppo piccolo'} |"
        )

    lines += [
        "",
        "Come leggere la tabella:",
        "",
        "- **JSON validi** sotto il 100% significa che il fallback e' entrato in funzione:",
        "  un modello che sbaglia spesso formato non e' affidabile come giudice automatico.",
        "- **Correlazione con F1** vicina a 1 indica che il judge ordina le pagine come la",
        "  metrica; vicina a 0 che sta dando voti scollegati dalla qualita' reale.",
        "- **Secondi medi** conta: il judge viene chiamato su ogni entry del Gold Standard.",
        "",
        "Attenzione: una correlazione bassa non condanna automaticamente il modello.",
        "La token_level_eval lavora su insiemi di token e ignora ordine e ripetizioni,",
        "quindi puo' premiare testi che un lettore umano giudicherebbe peggiori. Vale la",
        "pena leggere i feedback in judge_benchmark_details.json prima di decidere.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Confronto fra i modelli judge")
    parser.add_argument("--models", nargs="+", default=CANDIDATE_MODELS,
                        help="modelli da confrontare (default: tutti e cinque)")
    parser.add_argument("--per-domain", type=int, default=3,
                        help="pagine da valutare per ogni dominio (default 3)")
    parser.add_argument("--pull", action="store_true",
                        help="scarica i modelli mancanti prima di iniziare")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL, dest="ollama_url",
                        help="indirizzo di Ollama (da host: http://localhost:11434)")
    args = parser.parse_args()

    # Va impostato prima di importare src.services.judge, che legge
    # OLLAMA_URL dall'ambiente al momento dell'import.
    global OLLAMA_URL
    OLLAMA_URL = args.ollama_url
    os.environ["OLLAMA_URL"] = args.ollama_url
    print(f"Ollama: {OLLAMA_URL}")

    print("Preparo il campione")
    samples = load_samples(args.per_domain)
    cases = prepare(samples)
    if not cases:
        raise SystemExit("Nessuna pagina utilizzabile: serve almeno un gold_text compilato.")
    print(f"  {len(cases)} pagine pronte\n")

    available = installed_models()
    results: dict[str, list[dict]] = {}

    for model in args.models:
        present = any(name == model or name.startswith(f"{model}:") for name in available)
        if not present:
            if not args.pull:
                print(f"[skip] {model} non installato (usa --pull per scaricarlo)")
                results[model] = []
                continue
            if not pull_model(model):
                results[model] = []
                continue

        print(f"\n=== {model} ===")
        results[model] = run_model(model, cases)

    summary = summarize(results)
    Path("judge_benchmark_summary.md").write_text(summary, encoding="utf-8")
    Path("judge_benchmark_details.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + summary)
    print("\nScritti judge_benchmark_summary.md e judge_benchmark_details.json")


if __name__ == "__main__":
    main()
