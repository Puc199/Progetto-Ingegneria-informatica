# Confronto dei modelli candidati come judge

| Modello | Voto medio | JSON validi | Secondi medi | Correlazione con F1 |
|---|---|---|---|---|
| llama3.2:3b | 4.00 | 100% | 7.6 | -0.676 |
| phi4-mini | 3.33 | 100% | 18.6 | -0.621 |
| qwen3:4b | 1.00 | 0% | 27.8 | campione troppo piccolo |
| ministral-3:3b | 4.17 | 100% | 13.1 | -0.926 |
| gemma4:e2b | 1.00 | 0% | 30.7 | campione troppo piccolo |

Come leggere la tabella:

- **JSON validi** sotto il 100% significa che il fallback e' entrato in funzione:
  un modello che sbaglia spesso formato non e' affidabile come giudice automatico.
- **Correlazione con F1** vicina a 1 indica che il judge ordina le pagine come la
  metrica; vicina a 0 che sta dando voti scollegati dalla qualita' reale.
- **Secondi medi** conta: il judge viene chiamato su ogni entry del Gold Standard.

Attenzione: una correlazione bassa non condanna automaticamente il modello.
La token_level_eval lavora su insiemi di token e ignora ordine e ripetizioni,
quindi puo' premiare testi che un lettore umano giudicherebbe peggiori. Vale la
pena leggere i feedback in judge_benchmark_details.json prima di decidere.