# Immagine di MariaDB con lo schema del progetto gia' incorporato.
#
# init.sql viene copiato in /docker-entrypoint-initdb.d/, che l'immagine
# ufficiale esegue automaticamente alla prima creazione del data directory.
#
# Perche' copiarlo invece di montarlo come volume: montare un singolo file su
# Docker Desktop per Windows richiede la condivisione del disco e si comporta
# in modo meno prevedibile del resto. Cosi' il compose non ha piu' nessun bind
# mount, e il progetto si comporta identico su Windows, macOS e Linux.
#
# Nota: qui non si tocca l'utente dell'immagine e non si normalizzano i fine
# riga. Per MariaDB il ritorno a capo e' spazio bianco come un altro, quindi
# un init.sql con CRLF viene eseguito correttamente; e cambiare USER
# rischierebbe di rompere l'entrypoint ufficiale, che ha bisogno dei propri
# privilegi per preparare il data directory. Il caso resta comunque coperto da
# .gitattributes, che impone LF a questo file.

FROM mariadb:11.7.2-ubi9

COPY init.sql /docker-entrypoint-initdb.d/01-init.sql

EXPOSE 3306
