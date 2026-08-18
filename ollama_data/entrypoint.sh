#!/bin/sh
# Entrypoint del container Ollama.
#
# L'immagine ufficiale avvia soltanto il server: il modello andrebbe scaricato
# a mano con "ollama pull". La consegna pero' richiede che il modello sia
# "importato automaticamente all'avvio" e che fra "docker compose up --build"
# e lo script di test non ci sia nessun passaggio intermedio.
#
# Quindi: si avvia il server in background, si aspetta che risponda, si
# scarica il modello e poi si resta in attesa del processo del server, che
# rimane il processo principale del container.

set -e

MODEL="${OLLAMA_MODEL:-llama3.2:3b}"

echo "[ollama] avvio del server"
ollama serve &
SERVER_PID=$!

# Il server impiega qualche secondo prima di accettare richieste.
echo "[ollama] attendo che il server risponda"
i=0
while [ "$i" -lt 60 ]; do
    if ollama list >/dev/null 2>&1; then
        break
    fi
    i=$((i + 1))
    sleep 1
done

if ! ollama list >/dev/null 2>&1; then
    echo "[ollama] il server non risponde dopo 60 secondi"
    exit 1
fi

# Se il modello e' gia' nel volume, pull esce subito senza riscaricare nulla.
if ollama list | grep -q "^${MODEL}"; then
    echo "[ollama] modello ${MODEL} gia' presente"
else
    echo "[ollama] scarico il modello ${MODEL} (la prima volta puo' richiedere alcuni minuti)"
    ollama pull "${MODEL}"
fi

echo "[ollama] pronto con il modello ${MODEL}"

# Il container resta vivo finche' vive il server.
wait "${SERVER_PID}"
