# Perche' il download dentro il container e' lento: tre cause, tre controlli.
# Uso, dalla root del progetto:  .\diagnosi_lentezza.ps1

Write-Host ""
Write-Host "=== 1. La CPU e' occupata dal judge? ===" -ForegroundColor Cyan
Write-Host "(se lab_ollama sta sopra il 100% di CPU, sta calcolando i giudizi"
Write-Host " e Chromium nel backend rallenta di conseguenza)"
docker stats --no-stream --format "  {{.Name}}`t CPU {{.CPUPerc}}`t MEM {{.MemUsage}}"

Write-Host ""
Write-Host "=== 2. Il precalcolo dei giudizi e' ancora in corso? ===" -ForegroundColor Cyan
$giudizi = docker compose logs --tail=200 backend 2>$null | Select-String "Giudizi calcolati"
if ($giudizi) {
    $giudizi | Select-Object -Last 3 | ForEach-Object { Write-Host "  $_" }
    Write-Host "  Se l'ultimo numero non e' ancora al totale, il thread sta lavorando." -ForegroundColor Yellow
} else {
    Write-Host "  nessuna riga: il precalcolo non e' in corso." -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 3. Cosa dice il backend sull'ultimo tentativo? ===" -ForegroundColor Cyan
docker compose logs --tail=30 backend 2>$null | Select-String "Crawl4AI|Parsing fallito|ERROR|WARNING" |
    Select-Object -Last 8 | ForEach-Object { Write-Host "  $_" }

Write-Host ""
Write-Host "=== 4. Il sito risponde a una richiesta semplice? ===" -ForegroundColor Cyan
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
try {
    $t = Measure-Command {
        $r = Invoke-WebRequest -Uri "https://www.basketball-reference.com/players/j/jordami01.html" `
                               -UserAgent $ua -UseBasicParsing -TimeoutSec 60
    }
    Write-Host "  HTTP $($r.StatusCode), $($r.Content.Length) caratteri in $([int]$t.TotalSeconds) secondi" -ForegroundColor Green
    Write-Host "  Il sito risponde: il problema e' il browser headless, non la rete."
} catch {
    $codice = $_.Exception.Response.StatusCode.value__
    if ($codice -eq 429) {
        Write-Host "  429: Basketball-Reference sta limitando il tuo IP." -ForegroundColor Red
        Write-Host "  Aspetta un'ora prima di riprovare."
    } else {
        Write-Host "  Errore: $($_.Exception.Message)" -ForegroundColor Red
    }
}
