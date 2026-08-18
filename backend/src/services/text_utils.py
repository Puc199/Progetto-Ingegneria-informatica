"""
Normalizzazione del testo di riferimento in ingresso.

Il Gold Standard si costruisce a mano: si seleziona il contenuto informativo
nel browser, si copia e si incolla. Quel gesto pero' non porta con se' solo
le lettere visibili. Il testo copiato da una pagina web contiene anche
caratteri di controllo Unicode che il browser usa per impaginare e che nessun
essere umano vede:

  U+FEFF                byte order mark, incollato all'inizio di ogni cella
  U+200B..U+200D        spazi a larghezza zero
  U+200E, U+200F        marcatori di direzione sinistra-destra
  U+202A..U+202E        marcatori bidirezionali, che TradingView mette
                        attorno a ogni numero
  U+2066..U+2069        isolatori direzionali
  U+00A0, U+202F, U+2007  spazi non separabili

Perche' contano. La metrica obbligatoria confronta insiemi di token separati
da spazio: '\\u202a4,43' e '4,43' sono due token diversi. Il parser questi
caratteri li toglie gia' (li rimuove BeautifulSoup insieme al resto del
rumore), il testo incollato no. Il risultato e' una divergenza sistematica
che non dipende dalla qualita' del parsing ma dal modo in cui il testo e'
arrivato nel database: su una scheda TradingView valeva circa nove punti di
F1.

La normalizzazione sta qui, cioe' nell'unico punto in cui un gold_text entra
nel sistema, e non dentro la metrica. La differenza non e' cosmetica: se la
si mettesse nella metrica, il database conserverebbe testo sporco e ogni
altro consumatore (la Web UI, il judge, un'esportazione) se lo ritroverebbe.
Normalizzare in ingresso significa che nel database c'e' una sola versione
del testo, ed e' quella giusta.

Non si tocca invece 'html_text': quello e' la risorsa come e' stata
scaricata, e va conservata cosi' com'e'.
"""

from __future__ import annotations

import re

# Caratteri invisibili: si rimuovono del tutto.
_INVISIBLE_RE = re.compile(
    "[﻿​‌‍‎‏‪‫‬‭‮"
    "⁦⁧⁨⁩]"
)

# Spazi "speciali": diventano spazi normali, non spariscono.
_SPACE_RE = re.compile("[    ]")


def normalize_gold_text(text: str) -> str:
    """
    Ripulisce un testo di riferimento incollato dal browser.

    Rimuove i caratteri di controllo invisibili, riporta gli spazi speciali
    a spazi normali, uniforma i fine riga e toglie gli spazi in coda alle
    righe. Non tocca le parole, la punteggiatura ne' l'ordine: il contenuto
    resta esattamente quello che la persona ha selezionato.
    """
    if not text:
        return ""

    text = _INVISIBLE_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)

    return text.strip()
