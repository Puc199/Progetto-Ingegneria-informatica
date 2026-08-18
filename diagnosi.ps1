# Diagnosi in dieci secondi: capisce se il container ha davvero il codice nuovo.
#
# Uso, dalla root del progetto:
#     .\diagnosi.ps1

Write-Host ""
Write-Host "=== 1. Il template DENTRO il container ha ancora il campo html_text? ===" -ForegroundColor Cyan
$occorrenze = docker exec lab_frontend sh -c "grep -c 'name=\`"html_text\`"' src/templates/gold_standard.html 2>/dev/null || echo 0"
Write-Host "   occorrenze di name=`"html_text`": $occorrenze"
if ($occorrenze -match '^\s*0\s*$') {
    Write-Host "   OK: il container ha il template nuovo." -ForegroundColor Green
} else {
    Write-Host "   PROBLEMA: il container ha ancora il template vecchio." -ForegroundColor Red
    Write-Host "   Il rebuild non ha preso i file. Vedi la sezione 'Se il container e' vecchio' nel LEGGIMI."
}

Write-Host ""
Write-Host "=== 2. Il gestore del salvataggio e' quello nuovo? ===" -ForegroundColor Cyan
$async = docker exec lab_frontend sh -c "grep -c 'async def gold_standard_save' src/frontend.py 2>/dev/null || echo 0"
Write-Host "   'async def gold_standard_save' trovato: $async"
if ($async -match '^\s*0\s*$') {
    Write-Host "   PROBLEMA: frontend.py nel container e' vecchio." -ForegroundColor Red
} else {
    Write-Host "   OK: frontend.py e' quello nuovo." -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 3. Il file sul disco (fuori dal container) ===" -ForegroundColor Cyan
$locale = (Select-String -Path "frontend\src\templates\gold_standard.html" -Pattern 'name="html_text"' -AllMatches).Count
Write-Host "   occorrenze sul disco: $locale"
if ($locale -eq 0) {
    Write-Host "   OK: il file sul disco e' aggiornato." -ForegroundColor Green
} else {
    Write-Host "   PROBLEMA: applica.ps1 non ha sostituito il file." -ForegroundColor Red
}

Write-Host ""
Write-Host "=== 4. Da quando gira il container frontend ===" -ForegroundColor Cyan
docker ps --filter "name=lab_frontend" --format "   {{.Names}}  creato {{.CreatedAt}}  stato {{.Status}}"

Write-Host ""
Write-Host "Manda l'output di questo script se il problema resta." -ForegroundColor Yellow
