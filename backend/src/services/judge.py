"""
LLM-as-Judge: valutazione qualitativa del parsing tramite Ollama.

Il modello riceve il testo prodotto dal parser e il testo di riferimento e
restituisce un punteggio da 1 a 5 con un feedback in linguaggio naturale.

Scelte di progetto
------------------
1. Responsabilita' separate fra i due messaggi, come visto a lezione: il
   ruolo, i criteri e il formato stanno nel messaggio 'system'; nel messaggio
   'user' ci sono solo i due testi da confrontare. Un system prompt fisso e'
   anche piu' facile da mettere a punto, perche' cambia una cosa sola.

2. Formato JSON imposto a monte. Ollama accetta "format": "json", che vincola
   la generazione a produrre JSON sintatticamente valido. E' molto piu'
   efficace che chiederlo a parole a un modello da 3 miliardi di parametri.
   Il fallback resta comunque implementato: e' obbligatorio da consegna, e
   "JSON valido" non garantisce "JSON con i campi giusti".

3. Temperatura bassa. Qui serve un giudizio ripetibile: la stessa coppia di
   testi deve dare lo stesso punteggio a due chiamate diverse. La creativita'
   e' esattamente cio' che non si vuole.

4. Testi troncati. La consegna lo consente esplicitamente, e su CPU e' la
   differenza fra una valutazione che finisce e una che va in timeout. Il
   troncamento avviene sui primi caratteri: l'inizio di una pagina e' dove si
   concentrano sia il contenuto informativo sia il boilerplate residuo, cioe'
   proprio cio' che il judge deve saper distinguere.

5. Il Markdown viene rimosso prima dell'invio. Il judge deve valutare il
   contenuto estratto, non la formattazione: lasciarlo penalizzerebbe il
   parser per aver fatto quello che la consegna gli chiede.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

import requests

from src.services.markdown_utils import remove_markdown

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
JUDGE_MAX_CHARS = int(os.getenv("JUDGE_MAX_CHARS", "2000"))
JUDGE_TIMEOUT = int(os.getenv("JUDGE_TIMEOUT", "180"))

MIN_SCORE = 1
MAX_SCORE = 5

SYSTEM_PROMPT = """You are a strict evaluator of web page text extraction.

You compare TEXT_EXTRACTED, produced by an automatic parser, against
GOLD_TEXT, the reference text a human copied by hand from the same page.

Judge only the informative content. Ignore differences in line breaks,
spacing and ordering of sections.

Penalise:
- boilerplate left in TEXT_EXTRACTED (navigation menus, cookie banners,
  advertisements, footers, related links)
- informative content present in GOLD_TEXT but missing from TEXT_EXTRACTED
- text that is cut off in the middle of a sentence
- repeated content

Scoring scale:
5 = the informative content matches, no boilerplate
4 = minor omissions or small amounts of noise
3 = clearly usable, but with visible omissions or leftover boilerplate
2 = a large part of the content is missing or the noise dominates
1 = the extraction is unusable

Reply with a single JSON object, nothing else:
{"score": <integer 1-5>, "feedback": "<one short sentence>"}"""

USER_TEMPLATE = """GOLD_TEXT:
{gold_text}

TEXT_EXTRACTED:
{parsed_text}"""

# Cattura un oggetto JSON dentro una risposta che contiene anche altro
# (capita con i modelli che premettono una frase di cortesia).
JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
FIRST_SCORE_RE = re.compile(r"\b([1-5])\b")


def _truncate(text: str) -> str:
    """Rimuove il Markdown e taglia il testo alla lunghezza massima."""
    plain = remove_markdown(text or "").strip()
    if len(plain) <= JUDGE_MAX_CHARS:
        return plain
    return plain[:JUDGE_MAX_CHARS] + " [...]"


def _clamp_score(value: Any) -> Optional[int]:
    """Converte il punteggio in un intero fra 1 e 5, o None se non e' un numero."""
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(MIN_SCORE, min(MAX_SCORE, score))


def _fallback(feedback: str, raw: str = "") -> dict:
    """
    Risposta usata quando il modello non produce un giudizio leggibile.

    Il punteggio e' il minimo, e parse_ok=False segnala che il valore non e'
    un giudizio ma una mancata risposta. Tenere traccia della differenza
    conta: la percentuale di risposte valide e' uno dei numeri che motivano
    la scelta del modello nel report.
    """
    if raw:
        logger.warning("Risposta del judge non interpretabile: %.300s", raw)
    return {
        "model_name": OLLAMA_MODEL,
        "judge_score": MIN_SCORE,
        "judge_feedback": feedback,
        "parse_ok": False,
    }


def _parse_response(content: str) -> dict:
    """
    Estrae punteggio e feedback dalla risposta del modello.

    Tre tentativi in ordine di affidabilita' decrescente: JSON completo,
    oggetto JSON annegato in altro testo, primo numero fra 1 e 5 nel testo.
    """
    content = (content or "").strip()
    if not content:
        return _fallback("Il modello non ha restituito alcuna risposta.")

    payload: Optional[dict] = None
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            payload = parsed
    except json.JSONDecodeError:
        match = JSON_OBJECT_RE.search(content)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = None

    if payload is not None:
        score = _clamp_score(payload.get("score", payload.get("judge_score")))
        if score is not None:
            feedback = payload.get("feedback") or payload.get("judge_feedback") or ""
            return {
                "model_name": OLLAMA_MODEL,
                "judge_score": score,
                "judge_feedback": str(feedback).strip() or "Nessun feedback fornito dal modello.",
                "parse_ok": True,
            }

    # Ultimo tentativo: il modello ha risposto a parole ma il numero c'e'.
    match = FIRST_SCORE_RE.search(content)
    if match:
        return {
            "model_name": OLLAMA_MODEL,
            "judge_score": int(match.group(1)),
            "judge_feedback": content[:300],
            "parse_ok": False,
        }

    return _fallback("Il modello non ha rispettato il formato JSON richiesto.", content)


def judge_available() -> bool:
    """
    Vero se Ollama risponde e ha il modello configurato.

    Usato da GET /status, che deve riportare lo stato dei componenti senza
    sollevare eccezioni.
    """
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        models = [m.get("name", "") for m in response.json().get("models", [])]
        return any(name.startswith(OLLAMA_MODEL.split(":")[0]) for name in models)
    except Exception:
        return False


def evaluate_judge(parsed_text: str, gold_text: str,
                   model_name: Optional[str] = None) -> dict:
    """
    Chiede all'LLM un giudizio sulla qualita' del testo estratto.

    Args:
        parsed_text: testo prodotto dal parser, eventualmente in Markdown.
        gold_text: testo di riferimento del Gold Standard.
        model_name: modello da usare; se assente si usa quello configurato.
                    Serve al confronto fra modelli in fase di scelta.

    Returns:
        Dizionario con model_name, judge_score (intero 1-5), judge_feedback
        e parse_ok. Non solleva mai: un judge che non risponde e' un caso
        previsto, non un errore del sistema.
    """
    model = model_name or OLLAMA_MODEL

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(
                gold_text=_truncate(gold_text),
                parsed_text=_truncate(parsed_text),
            )},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_predict": 200,
        },
    }

    try:
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=JUDGE_TIMEOUT)
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
    except requests.Timeout:
        result = _fallback(f"Il modello {model} non ha risposto entro {JUDGE_TIMEOUT} secondi.")
        result["model_name"] = model
        return result
    except Exception as exc:
        result = _fallback(f"Ollama non raggiungibile: {exc}")
        result["model_name"] = model
        return result

    result = _parse_response(content)
    result["model_name"] = model
    return result
