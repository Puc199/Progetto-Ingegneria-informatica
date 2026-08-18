# Immagine di Ollama con l'entrypoint del progetto gia' incorporato.
#
# Perche' non montare semplicemente lo script come volume: su Windows il file
# puo' arrivare con i fine riga CRLF, e /bin/sh dentro il container fallisce.
# Copiandolo in fase di build possiamo normalizzarlo qui, una volta per tutte,
# senza dipendere dalla configurazione git di chi costruisce l'immagine.
# In piu' si evita del tutto il bind mount di un singolo file, che su Docker
# Desktop richiede la condivisione del disco ed e' una fonte di attrito in meno.

FROM ollama/ollama:latest

COPY entrypoint.sh /entrypoint.sh

# Rimuove eventuali \r e rende lo script eseguibile: cosi' funziona anche se
# arriva da un checkout Windows o da uno zip che ha perso i permessi.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 11434

ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]
