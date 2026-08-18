# Corregge il dominio delle righe gia' inserite e ricostruisce il backend.
#
# DOVE METTERE I FILE (scompatta lo zip dove vuoi, lo script fa il resto):
#   files\backend\src\server.py  ->  backend\src\server.py del progetto
#
# Uso:  .\ripara.ps1
#       oppure  .\ripara.ps1 -Root C:\Users\pucci\Progetto-Ingegneria-Informatica

param([string]$Root)

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

if (-not $Root) {
    $Root = Trova-Root -Partenza $PSScriptRoot
    if (-not $Root) { $Root = Trova-Root -Partenza (Get-Location).Path }
}
if (-not $Root) {
    Write-Host "Root del progetto non trovata. Usa -Root <percorso>." -ForegroundColor Red
    exit 1
}
$Root = (Resolve-Path $Root).Path
Write-Host "Progetto: $Root" -ForegroundColor Cyan

# --- 1. sostituzione del file ---
$src  = Join-Path $PSScriptRoot "files\backend\src\server.py"
$dest = Join-Path $Root "backend\src\server.py"

if (-not (Test-Path $src)) {
    Write-Host "server.py non trovato nello zip. Scompattalo mantenendo la struttura." -ForegroundColor Red
    exit 1
}

$backup = Join-Path $Root "backup_pre_fix_dominio"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item $dest (Join-Path $backup "server.py") -Force
Copy-Item $src $dest -Force
Write-Host "  aggiornato backend\src\server.py (backup in backup_pre_fix_dominio\)" -ForegroundColor Green

Push-Location $Root
try {
    # --- 2. correzione delle righe gia' scritte con il dominio sbagliato ---
    Write-Host ""
    Write-Host "Correzione del dominio nelle righe gia' inserite..." -ForegroundColor Cyan

    $sql = @"
UPDATE web_resources
SET domain = 'www.basketball-reference.com'
WHERE domain = 'basketball-reference.com';
SELECT domain, COUNT(*) AS righe FROM web_resources GROUP BY domain;
"@
    $sql | docker exec -i lab_mariadb mariadb -u lab_user -plab_password parsing_db

    # --- 3. ricostruzione del backend ---
    Write-Host ""
    Write-Host "Ricostruzione del backend..." -ForegroundColor Cyan
    docker compose up --build -d backend
    if ($LASTEXITCODE -ne 0) { throw "docker compose up ha restituito $LASTEXITCODE" }

    Start-Sleep -Seconds 8

    # --- 4. verifica ---
    Write-Host ""
    Write-Host "Verifica: pagine in attesa di gold_text per dominio" -ForegroundColor Cyan
    $domini = (Invoke-RestMethod -Uri "http://localhost:8003/domains").domains
    foreach ($d in $domini) {
        $enc  = [uri]::EscapeDataString($d)
        try {
            $res  = (Invoke-RestMethod -Uri "http://localhost:8003/web_resource_urls?domain=$enc").web_resource_urls
            $gold = (Invoke-RestMethod -Uri "http://localhost:8003/gold_standard_urls?domain=$enc").gold_standard_urls
            Write-Host ("  {0,-32} scaricate {1,3}   con testo {2,3}   in attesa {3,3}" -f `
                        $d, $res.Count, $gold.Count, ($res.Count - $gold.Count))
        } catch {
            Write-Host "  $d : il backend non risponde ancora, riprova fra qualche secondo" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    Write-Host "Ricarica http://localhost:8004/gold-standard scrivendo l'indirizzo nella barra." -ForegroundColor Yellow
}
finally {
    Pop-Location
}
