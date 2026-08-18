# Salvataggio: l'HTML non passa più dal browser

La tua diagnosi era esatta, incluso il perché LVMH passava e `eurozone-inflation` no. Ho corretto il flusso, e l'ho esteso anche a 1b — lì il problema esisteva identico, si sarebbe solo manifestato più tardi.

## Come applicare

```powershell
cd C:\Users\pucci\Progetto-Ingegneria-Informatica
.\applica.ps1
docker compose up --build -d frontend
```

Solo il frontend: il backend non cambia. Poi **ricarica con Ctrl+F5** — il browser può avere in cache il vecchio form, che contiene ancora il campo nascosto con l'HTML, e in quel caso l'errore si ripresenterebbe anche con il codice nuovo.

Cambiano due file, `frontend/src/frontend.py` e `frontend/src/templates/gold_standard.html`. Lo script fa una copia di sicurezza in `backup_pre_fix_upload\`.

## Cosa cambia

Prima l'HTML faceva un viaggio assurdo: backend → browser (dentro un campo nascosto) → backend. Su una pagina da 543.893 caratteri quel campo supera il megabyte e `python-multipart` rifiuta la parte prima ancora che la richiesta arrivi al gestore — motivo per cui l'errore compariva anche con la textarea vuota.

Ora **la risorsa web viene salvata al momento del download**, non al submit:

- **1a (dal database)** — l'HTML è già in `web_resources` e non si tocca. Il form manda solo `url` e `gold_text`.
- **1b (download nuovo)** — appena la pagina è scaricata, il frontend chiama `/add_web_resource`. Da quel momento l'HTML è nel database, e anche qui il form manda solo `url` e `gold_text`.

L'HTML fa un solo viaggio, dal backend al database. Il campo nascosto non esiste più.

Il vincolo di integrità referenziale resta soddisfatto: quando premi Salva, la risorsa web esiste già, quindi la foreign key di `gold_standard` trova la sua riga. La differenza è solo *quando* viene creata.

## Un effetto collaterale, che è un miglioramento

Se scarichi una pagina con 1b e poi cambi idea senza salvare il testo, la risorsa web resta nel database senza gold standard. Non è un problema: ricompare nell'elenco **1a in attesa**, quindi la ritrovi e la completi quando vuoi. Se invece non la vuoi più, il pulsante "Tutta la risorsa" la rimuove.

È anche il comportamento corretto rispetto alla consegna, che tiene `web_resources` e `gold_standard` come tabelle distinte proprio perché una pagina scaricata può esistere senza testo di riferimento.

## Verifica

Riprova con `eurozone-inflation`, che è quella che falliva. Deve salvare senza errori.

```powershell
curl "http://localhost:8003/gold_standard_urls?domain=global.morningstar.com"
```

Se `eurozone-inflation` compare nell'elenco, è fatta.

## Nota per il report

Vale la pena un accenno nella sezione sull'organizzazione del codice: è un buon esempio di come la separazione fra `web_resources` e `gold_standard` non sia solo formale. Le due tabelle hanno tempi di vita diversi — la risorsa nasce al download, il testo di riferimento nasce quando un umano lo scrive — e il flusso della UI ora rispecchia quella differenza invece di forzarli in un'unica operazione.

Se te lo chiedono all'orale, la versione breve è: *l'HTML non deve attraversare il browser, perché il browser non è la sorgente di quel dato.*

## Poi

Riprendi da dove eri: dieci testi per Morningstar, poi TradingView dopo aver cancellato le due pagine `/news/`, poi cinque nuove pagine ciascuno per Wikipedia e Basketball-Reference.

Quando i quattro domini sono a dieci, `docker compose restart backend` per far ricalcolare i giudizi mancanti, e poi dimmelo: rimisuro tutto e prepariamo report, checklist per la VM Ubuntu e domande dell'orale.
