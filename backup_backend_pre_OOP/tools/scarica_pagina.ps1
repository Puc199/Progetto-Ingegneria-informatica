# Scarica una pagina e la salva in web_resources, senza passare da Crawl4AI.
#
# Perche' esiste: il download dentro il container apre un Chromium headless a
# ogni richiesta. Su pagine grandi, o quando la CPU e' occupata dal calcolo dei
# giudizi dell'LLM, puo' superare il timeout della Web UI. Wikipedia e
# Basketball-Reference sono pero' renderizzate lato server: il loro HTML e'
# completo gia' nella prima risposta HTTP, quindi per costruire il Gold
# Standard un download semplice basta e avanza.
#
# Nota per l'orale: questo tocca solo COME si popola il Gold Standard.
# Il parser continua a usare Crawl4AI, che resta la libreria richiesta dalla
# consegna, e la valutazione gira sempre sull'HTML statico del database.
#
# Uso (dalla root del progetto):
#
#   .\backend\tools\scarica_pagina.ps1 -Url "https://www.basketball-reference.com/players/j/jordami01.html"
#
#   # piu' pagine in un colpo solo:
#   .\backend\tools\scarica_pagina.ps1 -Url @(
#       "https://www.basketball-reference.com/players/j/jordami01.html",
#       "https://www.basketball-reference.com/players/c/curryst01.html"
#   )
#
#   # da un file con un URL per riga:
#   .\backend\tools\scarica_pagina.ps1 -File .\urls_bbref.txt

param(
    [string[]]$Url,
    [string]$File,
    [string]$ApiBase = "http://localhost:8003",
    [int]$PausaSecondi = 4
)

$ErrorActionPreference = "Stop"

# Basketball-Reference limita esplicitamente le richieste automatiche e
# risponde 429 se si esagera. Una pausa fra un download e l'altro evita di
# farsi bloccare l'indirizzo IP per un'ora.
$UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
             "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

$MinCaratteri = 5000

if ($File) {
    if (-not (Test-Path $File)) {
        Write-Host "File non trovato: $File" -ForegroundColor Red
        exit 1
    }
    $Url = Get-Content $File | Where-Object { $_.Trim() -and -not $_.StartsWith("#") }
}

if (-not $Url) {
    Write-Host "Serve -Url oppure -File." -ForegroundColor Red
    Write-Host '  .\backend\tools\scarica_pagina.ps1 -Url "https://..."'
    exit 1
}

$ok = 0
$falliti = 0
$indice = 0

foreach ($u in $Url) {
    $indice++
    $u = $u.Trim()
    Write-Host ""
    Write-Host "[$indice/$($Url.Count)] $u" -ForegroundColor Cyan

    try {
        $risposta = Invoke-WebRequest -Uri $u -UserAgent $UserAgent -UseBasicParsing -TimeoutSec 60
    } catch {
        $codice = $_.Exception.Response.StatusCode.value__
        if ($codice -eq 429) {
            Write-Host "  429: il sito sta limitando le richieste." -ForegroundColor Red
            Write-Host "  Basketball-Reference blocca l'IP per circa un'ora se si insiste."
            Write-Host "  Aspetta e riprova piu' tardi."
            exit 1
        }
        Write-Host "  Download fallito: $($_.Exception.Message)" -ForegroundColor Red
        $falliti++
        continue
    }

    # L'HTML viene ricostruito dai byte grezzi in UTF-8: lasciando decidere a
    # PowerShell, le pagine senza charset dichiarato arriverebbero storpiate.
    try {
        $html = [System.Text.Encoding]::UTF8.GetString($risposta.RawContentStream.ToArray())
    } catch {
        $html = $risposta.Content
    }

    if ($html.Length -lt $MinCaratteri) {
        Write-Host "  Solo $($html.Length) caratteri: pagina di errore o blocco. La salto." -ForegroundColor Red
        $falliti++
        continue
    }

    Write-Host "  scaricati $($html.Length) caratteri, salvo nel database..."

    $corpo  = @{ url = $u; html_text = $html } | ConvertTo-Json -Depth 5 -Compress
    $bytes  = [System.Text.Encoding]::UTF8.GetBytes($corpo)

    try {
        $esito = Invoke-RestMethod -Uri "$ApiBase/add_web_resource" -Method Post -Body $bytes `
                                   -ContentType "application/json; charset=utf-8" -TimeoutSec 180
        Write-Host "  salvato ($($esito.status))" -ForegroundColor Green
        $ok++
    } catch {
        $messaggio = $_.Exception.Message
        if ($_.ErrorDetails.Message) {
            try { $messaggio = ($_.ErrorDetails.Message | ConvertFrom-Json).detail } catch { }
        }
        Write-Host "  salvataggio fallito: $messaggio" -ForegroundColor Red
        $falliti++
    }

    if ($indice -lt $Url.Count) { Start-Sleep -Seconds $PausaSecondi }
}

Write-Host ""
Write-Host "Riepilogo: $ok salvate, $falliti fallite." -ForegroundColor Cyan
Write-Host ""
Write-Host "Ora vai su http://localhost:8004/gold-standard, scegli il dominio e"
Write-Host "usa il riquadro 1a: le pagine sono nel database e aspettano il testo."
