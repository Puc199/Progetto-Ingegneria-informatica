# L'errore persiste — diagnosi e una via che lo aggira

Se l'errore è identico anche con la textarea quasi vuota, il campo grande è ancora nella richiesta. Le cause possibili sono due, e si distinguono in dieci secondi.

## Prima: capire quale delle due è

Scompatta lo zip nella root del progetto e lancia:

```powershell
.\diagnosi.ps1
```

Guarda **dentro il container**, non sul disco. La differenza è tutta lì: se il file sul disco è aggiornato ma quello nel container no, il rebuild non ha preso le modifiche — ed è la causa più probabile, perché il `detail` grezzo che vedi è la risposta di errore del frontend, quindi è il frontend a rifiutare il form, e lo farebbe solo se il template servito contenesse ancora il campo nascosto.

L'altra causa possibile è la cache del browser: la pagina che hai davanti è quella vecchia, con il campo nascosto già dentro l'HTML, e premere Salva la rispedisce così com'è anche se il server è aggiornato.

## Poi: applicare, forzando il rebuild

```powershell
.\applica.ps1
```

Fa tre cose che il tentativo precedente non faceva:

- `docker compose build --no-cache frontend` — se il rebuild normale aveva riusato un livello in cache, questo lo esclude
- `--force-recreate` — ricrea il container anche se l'immagine gli sembra uguale
- rilancia la diagnosi alla fine, così vedi subito se è a posto

Poi, nel browser: apri `http://localhost:8004/gold-standard` **da zero**, non ricaricando la pagina che hai davanti. Se torni indietro su una pagina risultato di un POST, il browser rispedisce il vecchio form.

Ho anche reso il gestore del salvataggio immune al problema: ora legge il form a mano con `request.form(max_part_size=...)` alzando il limite a 8 MB, invece di usare i parametri `Form()` di FastAPI, che quel limite non lo lasciano configurare. Anche se un campo grande arrivasse comunque, viene accettato.

## Intanto: una via che non passa dai form

Questa la puoi usare subito, funziona a prescindere dal problema di sopra, ed è **onestamente più veloce** per trenta pagine. Il testo viaggia come JSON, che il limite dei campi multipart non ce l'ha proprio.

Il giro diventa: selezioni il testo nel browser, `Ctrl+C`, e poi un comando.

```powershell
# 1. copia il testo informativo dalla pagina (Ctrl+C)
# 2. poi:
.\backend\tools\aggiungi_gold.ps1 -Url "https://global.morningstar.com/en-gb/markets/eurozone-inflation..."
```

Legge gli appunti, lo manda a `/add_gold_standard` e ti dice a quante entry sei arrivato per quel dominio.

Comandi utili:

```powershell
# quante ne mancano, per dominio
.\backend\tools\aggiungi_gold.ps1 -Stato

# quali pagine di un dominio aspettano ancora il testo
.\backend\tools\aggiungi_gold.ps1 -Mancanti "global.morningstar.com"

# da file invece che dagli appunti
.\backend\tools\aggiungi_gold.ps1 -Url "https://..." -File .\testo.txt
```

Due accortezze che ci ho messo dentro: il testo viene codificato in UTF-8 a mano, perché passando una stringa PowerShell userebbe la codifica di sistema e le lettere accentate arriverebbero storpiate nel database; e se copi meno di 400 caratteri chiede conferma, perché quasi sempre significa che hai preso solo il titolo.

La risorsa web deve già esistere nel database — per le pagine caricate dai JSON all'avvio è così. Se una pagina non c'è, la scarichi dal riquadro 1b della UI e poi usi il comando.

## Se il container resta vecchio

Nel caso raro in cui nemmeno `--no-cache` basti:

```powershell
docker compose stop frontend
docker compose rm -f frontend
docker rmi progetto-ingegneria-informatica-frontend
docker compose up --build -d frontend
```

Il nome dell'immagine lo vedi con `docker images | Select-String frontend`.

## Se resta comunque

Mandami l'output di `.\diagnosi.ps1` e le ultime righe di `docker compose logs frontend`. Con quelli capisco esattamente dove si ferma, invece di tirare a indovinare da qui.

Nel frattempo `aggiungi_gold.ps1` ti sblocca comunque: puoi compilare tutti e trenta i gold standard senza toccare la UI.
