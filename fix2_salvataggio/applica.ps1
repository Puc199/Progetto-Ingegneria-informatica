# Sostituisce i file e ricostruisce il frontend forzando il rebuild.
#
# Uso, dalla root del progetto:
#     .\applica.ps1
# Se PowerShell blocca lo script:
#     powershell -ExecutionPolicy Bypass -File .\applica.ps1

$ErrorActionPreference = "Stop"

if (-not (Test-Path "docker-compose.yaml")) {
    Write-Host "Non sei nella root del progetto." -ForegroundColor Red
    exit 1
}

$sorgente = Join-Path $PSScriptRoot "files"
$fileAttesi = @(
    "frontend\src\frontend.py",
    "frontend\src\templates\gold_standard.html",
    "backend\tools\aggiungi_gold.ps1"
)

$backup = "backup_pre_fix2"
if (-not (Test-Path $backup)) { New-Item -ItemType Directory -Path $backup | Out-Null }

foreach ($f in $fileAttesi) {
    if (Test-Path $f) {
        $dest = Join-Path $backup $f
        New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
        Copy-Item $f $dest -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $f) | Out-Null
    Copy-Item (Join-Path $sorgente $f) $f -Force
    Write-Host "  aggiornato $f" -ForegroundColor Green
}

Write-Host ""
Write-Host "Ricostruzione del frontend SENZA cache..." -ForegroundColor Cyan
Write-Host "(--no-cache: se il rebuild normale non aveva preso i file, questo lo forza)"
docker compose build --no-cache frontend
docker compose up -d --force-recreate frontend

Write-Host ""
Write-Host "Verifica:" -ForegroundColor Cyan
.\diagnosi.ps1
