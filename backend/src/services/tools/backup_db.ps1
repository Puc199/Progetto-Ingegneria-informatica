# Copia di sicurezza del database, in un file singolo.
#
# Perche' esiste: i gold_text vivono in MariaDB dentro un volume Docker. Un
# "docker compose down -v" o un "docker volume rm" lo cancellano senza chiedere
# conferma, e con lui ore di lavoro manuale. Questo comando mette al riparo
# tutto in pochi secondi.
#
# Il file finisce FUORI dalla cartella del progetto, in ..\backup_progetto\,
# cosi' non puo' finire per sbaglio nello zip di consegna e sopravvive anche se
# la cartella del progetto viene ricreata.
#
# Uso (dalla root del progetto):
#
#   .\backend\tools\backup_db.ps1              crea una copia
#   .\backend\tools\backup_db.ps1 -Elenca      mostra le copie esistenti
#   .\backend\tools\backup_db.ps1 -Ripristina ..\backup_progetto\nomefile.sql

param(
    [switch]$Elenca,
    [string]$Ripristina
)

$ErrorActionPreference = "Stop"

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
if (-not $Root) { Write-Host "Root del progetto non trovata." -ForegroundColor Red; exit 1 }
$Root = (Resolve-Path $Root).Path

$CartellaBackup = Join-Path (Split-Path $Root -Parent) "backup_progetto"
New-Item -ItemType Directory -Force -Path $CartellaBackup | Out-Null

# --- elenco delle copie esistenti ---

if ($Elenca) {
    Write-Host ""
    Write-Host "Copie in $CartellaBackup" -ForegroundColor Cyan
    $file = Get-ChildItem $CartellaBackup -Filter "*.sql" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending
    if (-not $file) {
        Write-Host "  nessuna copia presente." -ForegroundColor Yellow
    } else {
        foreach ($f in $file) {
            $mb = [math]::Round($f.Length / 1MB, 1)
            Write-Host ("  {0}   {1,6} MB   {2}" -f $f.LastWriteTime.ToString("dd/MM HH:mm"), $mb, $f.Name)
        }
    }
    exit 0
}

# --- ripristino ---

if ($Ripristina) {
    if (-not (Test-Path $Ripristina)) {
        Write-Host "File non trovato: $Ripristina" -ForegroundColor Red
        exit 1
    }
    Write-Host "Ripristino da $Ripristina" -ForegroundColor Cyan
    Write-Host "Il contenuto attuale del database verra' sostituito." -ForegroundColor Yellow
    $conferma = Read-Host "Procedere? (s/N)"
    if ($conferma -ne "s") { Write-Host "Annullato."; exit 0 }

    Get-Content $Ripristina -Raw | docker exec -i lab_mariadb mariadb -u lab_user -plab_password parsing_db
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Ripristino fallito." -ForegroundColor Red
        exit 1
    }

    Write-Host "Ripristinato. Riavvio il backend per rileggere i dati..." -ForegroundColor Green
    Push-Location $Root
    try { docker compose restart backend } finally { Pop-Location }
    exit 0
}

# --- creazione della copia ---

$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$percorso = Join-Path $CartellaBackup "parsing_db_$stamp.sql"

Write-Host "Copia del database in corso..." -ForegroundColor Cyan

# --single-transaction evita di bloccare le tabelle durante il dump.
docker exec lab_mariadb mariadb-dump -u lab_user -plab_password --single-transaction parsing_db |
    Out-File -FilePath $percorso -Encoding utf8

if ($LASTEXITCODE -ne 0 -or -not (Test-Path $percorso)) {
    Write-Host "Copia fallita. Il container lab_mariadb e' avviato?" -ForegroundColor Red
    exit 1
}

$mb = [math]::Round((Get-Item $percorso).Length / 1MB, 1)
if ($mb -lt 0.1) {
    Write-Host "Il file e' quasi vuoto ($mb MB): qualcosa non ha funzionato." -ForegroundColor Red
    exit 1
}

Write-Host "Salvato: $percorso  ($mb MB)" -ForegroundColor Green
Write-Host ""
Write-Host "Sta fuori dalla cartella del progetto, quindi non finisce nello zip"
Write-Host "e sopravvive a 'docker compose down -v'."
