# Progetto Esonero 1: Pipeline di Parsing Web

Progetto per il corso di Laboratorio di Ingegneria Informatica (A.A. 2025/2026).

## Descrizione
Pipeline end-to-end per l'acquisizione, il parsing e la valutazione di documenti web da domini eterogenei (Wikipedia + 3 domini assegnati).

## Componenti
- **Backend**: FastAPI con parser specifici (Crawl4AI), servizi di valutazione (token-level) e API REST.
- **Frontend**: Web UI basata su HTML/Jinja2 per il testing della pipeline.

## Requisiti
- Docker
- Docker Compose

## Installazione e Avvio
Per avviare il sistema, eseguire dalla cartella principale:

```bash
docker compose up --build
```

Il backend sarà disponibile sulla porta `8003`, il frontend sulla porta `8004`.

## Struttura del Progetto
- `backend/`: API FastAPI, parser, servizi di evaluation e schemi Pydantic.
- `frontend/`: Server UI basato su Jinja2.
- `gsdata/`: File JSON contenenti il Gold Standard per i domini.
- `domains.json`: Elenco dei domini supportati.

## Test automatico
Per verificare il corretto funzionamento dell'API, utilizzare lo script di test ufficiale fornito dai docenti.
