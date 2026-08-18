# Esporta il Gold Standard dal database ai file JSON di gs_data/.
#
# Perche' serve: i gold_text scritti dalla Web UI vivono in MariaDB, ma la
# consegna chiede che i file JSON del Gold Standard siano dentro il progetto,
# ed e' da quei file che il sistema si ripopola al primo avvio su una macchina
# pulita. Senza questo passaggio, sul computer del docente il database
# nascerebbe con le sole entry presenti nei JSON vecchi.
#
# Prima di esportare viene creata una copia di sicurezza del database in
# ..\backup_progetto\: i JSON si possono sempre riscrivere partendo da un dump,
# il contrario no.
#
# Nota sulla codifica
# -------------------
# Le risposte del backend si leggono con Invoke-WebRequest e si decodificano
# a mano in UTF-8. Invoke-RestMethod, su Windows PowerShell 5.1, quando la
# risposta non dichiara il charset interpreta i byte come ISO-8859-1: le
# lettere accentate diventano due caratteri ('e' accentata -> 'Ã¨') e
# riscrivendo il file in UTF-8 l'errore si fissa nel JSON. E' cosi' che i
# file di gs_data/ si erano riempiti di 'Ã¨' e 'â€™'.
#
# Uso (dalla root del progetto, con lo stack avviato):
#
#   .\backend\tools\esporta_gs.ps1
#   .\backend\tools\esporta_gs.ps1 -Verifica     # controlla e basta, non scrive

param(
    [string]$ApiBase = "http://localhost:8003",
    [switch]$Verifica
)

$ErrorActionPreference = "Stop"

# Nomi dei file gia' usati nel progetto: si riscrivono quelli invece di
# crearne di nuovi, altrimenti il caricamento iniziale leggerebbe due volte
# le stesse pagine da file diversi.
$NomiFile = @{
    "en.wikipedia.org"             = "wikipedia_gs.json"
    "www.basketball-reference.com" = "basketballreference_gs.json"
    "global.morningstar.com"       = "globalmorningstar_gs.json"
    "it.tradingview.com"           = "ittradingview_gs.json"
}

function Trova-Root {
    param([string]$Partenza)
    $dir = $Partenza
    for ($i = 0; $i -lt 6 -and $dir; $i++) {
        if (Test-Path (Join-Path $dir "docker-compose.yaml")) { return $dir }
        $padre = Split-Path $dir -Parent
        if ($padre -eq $dir) { break }
        $dir = $padre
    }
    return $null
}

$Root = Trova-Root -Partenza $PSScriptRoot
if (-not $Root) { $Root = Trova-Root -Partenza (Get-Location).Path }
if (-not $Root) {
    Write-Host "Root del progetto non trovata." -ForegroundColor Red
    exit 1
}
$Root = (Resolve-Path $Root).Path
$GsDir = Join-Path $Root "gs_data"
New-Item -ItemType Directory -Force -Path $GsDir | Out-Null

Write-Host "Progetto : $Root"
Write-Host "Cartella : $GsDir"
Write-Host ""

# Copia di sicurezza prima di toccare qualsiasi cosa.
if (-not $Verifica) {
    $backupScript = Join-Path $PSScriptRoot "backup_db.ps1"
    if (Test-Path $backupScript) {
        & $backupScript
        Write-Host ""
    } else {
        Write-Host "backup_db.ps1 non trovato: procedo senza copia di sicurezza." -ForegroundColor Yellow
    }
}

function Leggi-Json {
    # Invoke-WebRequest restituisce anche i byte grezzi: si decodificano
    # esplicitamente in UTF-8 e solo dopo si converte il JSON.
    param([string]$Indirizzo, [int]$Timeout = 600)

    $risposta = Invoke-WebRequest -Uri $Indirizzo -UseBasicParsing -TimeoutSec $Timeout
    $testo = [System.Text.Encoding]::UTF8.GetString($risposta.RawContentStream.ToArray())
    return $testo | ConvertFrom-Json
}

try {
    $domini = (Leggi-Json -Indirizzo "$ApiBase/domains" -Timeout 30).domains
} catch {
    Write-Host "Backend non raggiungibile su $ApiBase." -ForegroundColor Red
    Write-Host "Avvia lo stack con 'docker compose up -d' e aspetta che finisca l'inizializzazione."
    exit 1
}

$totale = 0
$problemi = @()

foreach ($dominio in $domini) {
    Write-Host "$dominio" -ForegroundColor Cyan

    $enc = [uri]::EscapeDataString($dominio)
    try {
        # Una sola chiamata per dominio: restituisce url, domain, title,
        # html_text e gold_text di ogni entry, cioe' esattamente il formato
        # del file JSON.
        $risposta = Leggi-Json -Indirizzo "$ApiBase/full_gold_standard?domain=$enc"
    } catch {
        Write-Host "  lettura fallita: $($_.Exception.Message)" -ForegroundColor Red
        $problemi += "$dominio : lettura fallita"
        continue
    }

    $entry = @($risposta.gold_standard)
    $conGold = @($entry | Where-Object { $_.gold_text -and $_.gold_text.Trim() }).Count
    $htmlSospetti = @($entry | Where-Object { -not $_.html_text -or $_.html_text.Length -lt 1000 }).Count

    Write-Host "  entry: $($entry.Count)   con gold_text: $conGold   html sospetti: $htmlSospetti"

    if ($entry.Count -lt 10)         { $problemi += "$dominio : solo $($entry.Count) entry (ne servono 10)" }
    if ($conGold -lt $entry.Count)   { $problemi += "$dominio : $($entry.Count - $conGold) entry senza gold_text" }
    if ($htmlSospetti -gt 0)         { $problemi += "$dominio : $htmlSospetti entry con html_text sospetto" }

    if ($Verifica) { continue }

    # Un file con meno entry di quello che sta gia' su disco quasi sempre
    # significa che il database e' stato ricreato e non contiene ancora tutto:
    # sovrascriverlo peggiorerebbe la situazione invece di salvarla.
    $nome = $NomiFile[$dominio]
    if (-not $nome) {
        $base = $dominio -replace '^www\.', '' -replace '\.(com|org|it|net|edu)$', ''
        $base = $base -replace '[.\-_]', ''
        $nome = "${base}_gs.json"
    }
    $percorso = Join-Path $GsDir $nome

    if (Test-Path $percorso) {
        try {
            $esistenti = @((Get-Content $percorso -Raw -Encoding UTF8 | ConvertFrom-Json))
            $goldEsistenti = @($esistenti | Where-Object { $_.gold_text -and $_.gold_text.Trim() }).Count
            if ($goldEsistenti -gt $conGold) {
                Write-Host "  ATTENZIONE: il file su disco ha $goldEsistenti gold_text, il database solo $conGold." -ForegroundColor Red
                Write-Host "  Non sovrascrivo: sarebbe una perdita. Controlla lo stato del database." -ForegroundColor Red
                $problemi += "$dominio : file NON sovrascritto (avrebbe perso $($goldEsistenti - $conGold) gold_text)"
                continue
            }
        } catch {
            # File illeggibile o malformato: si procede comunque a riscriverlo.
        }
    }

    # Si riscrivono solo i cinque campi previsti dal formato del Gold Standard.
    $pulite = $entry | ForEach-Object {
        [ordered]@{
            url       = $_.url
            domain    = $_.domain
            title     = $_.title
            html_text = $_.html_text
            gold_text = $_.gold_text
        }
    }

    $json = $pulite | ConvertTo-Json -Depth 10

    # UTF-8 SENZA BOM: Out-File aggiungerebbe i tre byte iniziali e il
    # json.loads() di Python fallirebbe con "Expecting value: line 1 column 1".
    $senzaBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($percorso, $json, $senzaBom)

    $mb = [math]::Round((Get-Item $percorso).Length / 1MB, 1)
    Write-Host "  scritto $nome ($mb MB)" -ForegroundColor Green
    $totale += $entry.Count
}

Write-Host ""
if ($problemi) {
    Write-Host "Da controllare:" -ForegroundColor Yellow
    foreach ($p in $problemi) { Write-Host "  - $p" }
} else {
    Write-Host "Tutti i domini hanno 10 entry complete." -ForegroundColor Green
}

if (-not $Verifica) {
    Write-Host ""
    Write-Host "Esportate $totale entry in totale."
}
