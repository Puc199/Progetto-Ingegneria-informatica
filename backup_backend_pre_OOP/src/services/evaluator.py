"""
Metriche di valutazione automatica dei parser.

Due metriche, che guardano la stessa coppia di testi da angolazioni diverse:

  token_level_eval    obbligatoria da consegna. Lavora su INSIEMI di token:
                      dice quanto contenuto e' stato catturato e quanto
                      rumore e' rimasto, ignorando ordine e ripetizioni.

  sequence_eval       aggiunta da noi. Lavora sulle SEQUENZE di token:
                      dice se il testo estratto scorre come l'originale.

La seconda copre il punto cieco della prima, che la consegna stessa segnala
quando avverte che "Buono e' condizione necessaria ma non sufficiente". Un
parser che restituisse tutte le parole giuste in ordine casuale, o che
ripetesse tre volte lo stesso paragrafo, otterrebbe un F1 token-level quasi
perfetto: sequence_eval invece crolla, perche' misura la sottosequenza
comune piu' lunga.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from src.services.markdown_utils import remove_markdown


def normalize(text: str) -> str:
    """
    Testo pronto per il confronto: senza Markdown, in minuscolo.

    La rimozione del Markdown e' necessaria perche' il parser produce
    Markdown mentre il Gold Standard e' testo semplice: senza questo passaggio
    si penalizzerebbe il parser per aver fatto quello che gli si chiede.
    """
    return remove_markdown(text or "").lower().strip()


def tokenize(text: str) -> set[str]:
    """Insieme dei token, cioe' parole separate da spazio, in minuscolo."""
    cleaned = normalize(text)
    if not cleaned:
        return set()
    return set(cleaned.split())


def tokenize_sequence(text: str) -> list[str]:
    """Lista dei token nell'ordine in cui compaiono, ripetizioni comprese."""
    cleaned = normalize(text)
    return cleaned.split() if cleaned else []


def _prf(overlap: int, predicted: int, gold: int) -> dict:
    """Precision, recall e F1 a partire dai tre conteggi."""
    if not predicted or not gold:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    precision = overlap / predicted
    recall = overlap / gold
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)

    return {"precision": precision, "recall": recall, "f1": f1}


def token_level_eval(parsed_text: str, gold_text: str) -> dict:
    """
    Metrica obbligatoria: sovrapposizione fra gli insiemi di token.

    Precision  quanti dei token estratti sono davvero nel Gold Standard
    Recall     quanti dei token del Gold Standard sono stati trovati
    F1         media armonica dei due
    """
    pred_tokens = tokenize(parsed_text)
    gold_tokens = tokenize(gold_text)

    return _prf(len(pred_tokens & gold_tokens), len(pred_tokens), len(gold_tokens))


def sequence_eval(parsed_text: str, gold_text: str) -> dict:
    """
    Metrica aggiuntiva: sovrapposizione fra le sequenze di token.

    Si basa sulla sottosequenza comune piu' lunga fra le due liste di token
    (la stessa idea di ROUGE-L, usata in letteratura per la valutazione dei
    riassunti). A differenza di token_level_eval tiene conto dell'ordine e
    delle ripetizioni, quindi penalizza:

      * i blocchi ripetuti, tipici dei parser che raccolgono lo stesso
        contenuto da piu' contenitori annidati;
      * il testo giusto ma scomposto, per esempio quando una tabella viene
        srotolata cella per cella perdendo la sequenza originale;
      * il boilerplate inserito in mezzo al contenuto, che spezza la
        sottosequenza comune anche quando le singole parole coincidono.

    SequenceMatcher usa un algoritmo che, per costruzione, non e' la LCS
    classica: cerca il blocco contiguo piu' lungo e ricorre sui due lati.
    Sulle nostre lunghezze e' la scelta giusta perche' e' nella libreria
    standard e resta veloce su liste di migliaia di token; il valore che
    produce e' leggermente conservativo rispetto alla LCS teorica.
    """
    pred_tokens = tokenize_sequence(parsed_text)
    gold_tokens = tokenize_sequence(gold_text)

    if not pred_tokens or not gold_tokens:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    matcher = SequenceMatcher(a=pred_tokens, b=gold_tokens, autojunk=False)
    common = sum(block.size for block in matcher.get_matching_blocks())

    return _prf(common, len(pred_tokens), len(gold_tokens))


def evaluate_all(parsed_text: str, gold_text: str) -> dict:
    """
    Esegue tutte le metriche implementate.

    Il formato e' quello richiesto da POST /evaluate: una chiave per metrica,
    con token_level_eval sempre presente.
    """
    return {
        "token_level_eval": token_level_eval(parsed_text, gold_text),
        "sequence_eval": sequence_eval(parsed_text, gold_text),
    }
