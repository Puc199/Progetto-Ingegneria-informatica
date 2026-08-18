# Pipeline di Parsing Web e Valutazione con LLM-as-Judge

Progetto finale per il corso di Laboratorio di Ingegneria Informatica
(A.A. 2025/2026).

Denis Fava (2018687) · Riccardo Pucci (1994172) · Alessandro Cantaressi (2129091)

## Descrizione

Data una URL appartenente a uno dei domini supportati, il sistema scarica la
pagina, ne estrae il contenuto informativo in Markdown, e ne misura la qualità
in due modi indipendenti: con metriche automatiche calcolate rispetto a un Gold
Standard costruito a mano, e con il giudizio di un LLM eseguito localmente.

Domini supportati:

- `en.wikipedia.org`
- `www.basketball-reference.com`
- `global.morningstar.com`
- `it.tradingview.com`

## Avvio

Requisiti: Docker e Docker Compose.

```bash
docker compose up --build
```

Non serve nessun altro passaggio. Al primo avvio il container MariaDB crea lo
schema, il container Ollama scarica il modello, e il backend popola il database
leggendo i file JSON di `gs_data/`, calcola le metriche e avvia in background il
precalcolo dei giudizi.

Il primo avvio richiede alcuni minuti, quasi tutti spesi a scaricare il modello
(circa 3 GB). Lo stato di avanzamento si segue con:

```bash
docker logs -f lab_backend
```

Il sistema è pronto quando compare `Application startup complete`.

| Servizio | Porta | Indirizzo |
|---|---|---|
| Backend REST | 8003 | http://localhost:8003 |
| Web UI | 8004 | http://localhost:8004 |
| MariaDB | 3306 | — |
| Ollama | 11434 | — |

## Struttura del progetto

```
backend/           API FastAPI, parser, servizi di valutazione e schemi Pydantic
  src/parsers/     BaseParser e le quattro sottoclassi, una per dominio
  src/services/    database, repository, evaluator, judge, bootstrap
  tools/           gs.py, strumenti da riga di comando per il Gold Standard
frontend/          Web UI in Jinja2, dialoga solo con le API REST
gs_data/           i quattro file JSON del Gold Standard (40 entry)
mariadb_data/      Dockerfile e init.sql con lo schema del database
ollama_data/       Dockerfile ed entrypoint che scarica il modello
domains.json       elenco dei domini supportati
report.pdf         relazione del progetto
```

## API REST

| Metodo | Endpoint | |
|---|---|---|
| POST | `/parse` | esegue il parser; con `local=true` usa l'HTML del database |
| GET | `/parse` | variante GET, stessi parametri |
| GET | `/domains` | domini supportati |
| GET | `/gold_standard` | una entry del Gold Standard |
| GET | `/gold_standard_urls` | URL con testo di riferimento, per dominio |
| GET | `/web_resource_urls` | URL scaricati, per dominio |
| GET | `/full_gold_standard` | tutte le entry di un dominio |
| POST | `/evaluate` | metriche fra testo estratto e riferimento |
| POST | `/evaluate_judge` | giudizio dell'LLM |
| GET | `/full_gs_eval` | valutazione aggregata di un dominio |
| POST | `/add_web_resource` | inserisce o aggiorna una risorsa web |
| POST | `/add_gold_standard` | inserisce o aggiorna un testo di riferimento |
| DELETE | `/web_resource` | rimuove una risorsa, e a cascata il suo gold standard |
| DELETE | `/gold_standard` | rimuove solo il testo di riferimento |
| GET | `/db_stats` | conteggi e metriche medie per dominio |
| GET | `/db_schema` | schema delle tabelle |
| GET | `/status` | stato dei componenti; risponde sempre 200 |

La documentazione interattiva generata da FastAPI è su
http://localhost:8003/docs.

## Web UI

Quattro pagine, su http://localhost:8004:

- **Home** — matricole, stato del sistema, domini supportati
- **Parser & Evaluation** — parsing live o locale, confronto fra testo grezzo,
  testo estratto e testo di riferimento, metriche e giudizio
- **Gold Standard** — aggiunta e rimozione di entry
- **Stats** — conteggi, metriche medie e giudizio medio per dominio

## Strumenti da riga di comando

`backend/tools/gs.py` gestisce il Gold Standard passando dalle API REST. Usa
solo la libreria standard di Python, quindi non richiede installazioni.

```bash
python3 backend/tools/gs.py stato                    # quante entry per dominio
python3 backend/tools/gs.py scarica URL...           # scarica pagine e le salva
python3 backend/tools/gs.py aggiungi URL FILE.txt    # salva un testo di riferimento
python3 backend/tools/gs.py misura URL               # metriche di una pagina
python3 backend/tools/gs.py misura-dominio           # metriche aggregate
python3 backend/tools/gs.py backup                   # copia di sicurezza del database
python3 backend/tools/gs.py esporta                  # riscrive i JSON di gs_data/
```

## Note

**Il Gold Standard è la fonte di verità.** I file JSON di `gs_data/` contengono
URL, dominio, titolo, HTML grezzo e testo di riferimento di ogni pagina. Il
database è una copia di lavoro: viene ripopolato da quei file al primo avvio su
una macchina pulita. Il parsing e le metriche si possono ricalcolare in qualsiasi
momento, un testo copiato a mano no.

**La valutazione lavora sempre sull'HTML statico** salvato nel database, mai
sulla pagina live: è ciò che la consegna richiede, ed è anche l'unico modo di
ottenere numeri confrontabili nel tempo su siti che cambiano ogni giorno.

**Configurazione.** Le variabili d'ambiente sono in `docker-compose.yaml`. Le
più utili: `OLLAMA_MODEL` (modello del judge), `JUDGE_MAX_CHARS` (troncamento
del testo inviato al modello), `JUDGE_ON_INIT` (precalcolo dei giudizi
all'avvio), `OLLAMA_KEEP_ALIVE` (quanto il modello resta in memoria).

## Test

Per verificare il funzionamento delle API, utilizzare lo script di test
ufficiale fornito dai docenti.
