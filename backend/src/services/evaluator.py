from collections import Counter
from src.services.markdown_utils import remove_markdown


def tokenize(text: str) -> list[str]:
    cleaned = remove_markdown(text).lower().strip()
    if not cleaned:
        return []
    return cleaned.split()


def token_level_eval(parsedtext: str, goldtext: str) -> dict:
    pred_tokens = tokenize(parsedtext)
    gold_tokens = tokenize(goldtext)

    if not pred_tokens or not gold_tokens:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0
        }

    pred_counter = Counter(pred_tokens)
    gold_counter = Counter(gold_tokens)

    overlap = sum((pred_counter & gold_counter).values())

    precision = overlap / len(pred_tokens) if pred_tokens else 0.0
    recall = overlap / len(gold_tokens) if gold_tokens else 0.0

    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1
    }