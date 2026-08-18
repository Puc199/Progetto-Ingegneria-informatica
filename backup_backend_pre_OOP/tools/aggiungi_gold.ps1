# Aggiunge un gold_text al database passando direttamente dalle API REST.
#
# Perche' esiste: copiare il testo dal browser e incollarlo in una textarea
# funziona, ma per trenta pagine e' lento, e un form HTML puo' inciampare nei
# limiti di dimensione dei campi. Qui il testo viaggia come JSON, che quei
# limiti non ce l'ha, e il giro si riduce a due gesti: copi dalla pagina,
# lanci il comando.
#
# La risorsa web deve gia' esistere nel database: e' il vincolo di integrita'
# referenziale fra gold_standard e web_resources. Per le pagine caricate dai
# JSON all'avvio e' gia' cosi'.
#
# Uso (dalla root del progetto):
#
#   # 1. seleziona il testo informativo nel browser e premi Ctrl+C
#   # 2. poi:
#   .\backend\tools\aggiungi_gold.ps1 -Url "https://global.morningstar.com/en-gb/funds/..."
#
#   # da un file invece che dagli appunti:
#   .\backend\tools\aggiungi_gold.ps1 -Url "https://..." -File .\testo.txt
#
#   # quante ne mancano, per dominio:
#   .\backend\tools\aggiungi_gold.ps1 -Stato
#
#   # cosa manca ancora in un dominio:
#   .\backend\tools\aggiungi_gold.ps1 -Mancanti "global.morningstar.com"

param(
    [string]$Url,
    [string]$File,
    [string]$Mancanti,
    [switch]$Stato,
    [string]$ApiBase = "http://localhost:8003"
)

$ErrorActionPreference = "Stop"

function Invia-Json {
    param([string]$Path, [hashtable]$Corpo)

    # Il corpo viene codificato a mano in UTF-8: passando una stringa,
    # PowerShell userebbe la codifica di sistema e le lettere accentate
    # arriverebbero al database storpiate.
    $json  = $Corpo | ConvertTo-Json -Depth 5 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)

    return Invoke-RestMethod -Uri "$ApiBase$Path" -Method Post -Body $bytes `
                             -ContentType "application/json; charset=utf-8"
}

function Mostra-Stato {
    $domini = (Invoke-RestMethod -Uri "$ApiBase/domains").domains
    Write-Host ""
    Write-Host ("{0,-32} {1,9} {2,9} {3,9}" -f "dominio", "scaricate", "con testo", "mancano")
    Write-Host ("-" * 62)

    foreach ($d in $domini) {
        $res  = (Invoke-RestMethod -Uri "$ApiBase/web_resource_urls?domain=$([uri]::EscapeDataString($d))").web_resource_urls
        $gold = (Invoke-RestMethod -Uri "$ApiBase/gold_standard_urls?domain=$([uri]::EscapeDataString($d))").gold_standard_urls
        $mancano = [Math]::Max(0, 10 - $gold.Count)
        $colore = if ($mancano -eq 0) { "Green" } else { "Yellow" }
        Write-Host ("{0,-32} {1,8} {2,8} {3,10}" -f $d, $res.Count, $gold.Count, $mancano) -ForegroundColor $colore
    }
    Write-Host ""
    Write-Host "La consegna chiede almeno 10 entry con gold_text per dominio."
}

function Mostra-Mancanti {
    param([string]$Dominio)
    $enc  = [uri]::EscapeDataString($Dominio)
    $res  = (Invoke-RestMethod -Uri "$ApiBase/web_resource_urls?domain=$enc").web_resource_urls
    $gold = (Invoke-RestMethod -Uri "$ApiBase/gold_standard_urls?domain=$enc").gold_standard_urls
    $pending = $res | Where-Object { $gold -notcontains $_ }

    Write-Host ""
    if (-not $pending) {
        Write-Host "Tutte le pagine di $Dominio hanno gia' un testo di riferimento." -ForegroundColor Green
        return
    }
    Write-Host "Pagine di $Dominio in attesa di gold_text ($($pending.Count)):" -ForegroundColor Cyan
    foreach ($u in $pending) { Write-Host "  $u" }
}

# --- modalita' informative ---

if ($Stato)    { Mostra-Stato; exit 0 }
if ($Mancanti) { Mostra-Mancanti -Dominio $Mancanti; exit 0 }

if (-not $Url) {
    Write-Host "Serve -Url. Esempi:" -ForegroundColor Red
    Write-Host '  .\backend\tools\aggiungi_gold.ps1 -Url "https://..."'
    Write-Host '  .\backend\tools\aggiungi_gold.ps1 -Stato'
    exit 1
}

# --- testo: da file oppure dagli appunti ---

if ($File) {
    if (-not (Test-Path $File)) {
        Write-Host "File non trovato: $File" -ForegroundColor Red
        exit 1
    }
    # ReadAllText e non Get-Content: -Raw restituisce una stringa a cui
    # PowerShell attacca delle proprieta' di servizio (PSPath, PSDrive,
    # PSProvider...). ConvertTo-Json serializza quelle invece del testo, e
    # il backend riceve un oggetto dove si aspetta una stringa: 422.
    $percorso = (Resolve-Path $File).Path
    $testo = [System.IO.File]::ReadAllText($percorso, [System.Text.Encoding]::UTF8)
    $sorgente = "file $File"
} else {
    $testo = [string](Get-Clipboard -Raw)
    $sorgente = "appunti"
}

if ([string]::IsNullOrWhiteSpace($testo)) {
    Write-Host "Il testo e' vuoto ($sorgente). Copia il testo informativo dalla pagina e riprova." -ForegroundColor Red
    exit 1
}

$caratteri = $testo.Length
Write-Host "URL    : $Url"
Write-Host "Testo  : $caratteri caratteri, da $sorgente"

# Una soglia bassa quasi sempre significa che sono stati copiati solo il
# titolo o poche righe: meglio chiedere conferma che riempire il gold
# standard di entry inutilizzabili.
if ($caratteri -lt 400) {
    Write-Host ""
    Write-Host "Attenzione: sono pochi caratteri per un testo informativo." -ForegroundColor Yellow
    $risposta = Read-Host "Salvare comunque? (s/N)"
    if ($risposta -ne "s") { Write-Host "Annullato."; exit 0 }
}

try {
    # Il cast a [string] e' una seconda rete di sicurezza: qualunque cosa sia
    # arrivata, nel JSON ci finisce testo semplice.
    $esito = Invia-Json -Path "/add_gold_standard" -Corpo @{ url = "$Url"; gold_text = [string]$testo }
} catch {
    $messaggio = $_.Exception.Message
    if ($_.ErrorDetails.Message) {
        try {
            $dettaglio = ($_.ErrorDetails.Message | ConvertFrom-Json).detail
            # Con un errore di validazione FastAPI manda una lista di oggetti,
            # non una stringa: senza questo controllo il messaggio usciva vuoto.
            if ($dettaglio -is [string]) { $messaggio = $dettaglio }
            elseif ($dettaglio) { $messaggio = ($dettaglio | ForEach-Object { $_.msg }) -join "; " }
        } catch {
            $messaggio = $_.ErrorDetails.Message
        }
    }
    if (-not $messaggio) { $messaggio = "errore senza descrizione" }
    Write-Host ""
    Write-Host "Salvataggio fallito: $messaggio" -ForegroundColor Red
    Write-Host ""
    Write-Host "Se dice che l'URL non e' in web_resources, la pagina non e' ancora"
    Write-Host "stata scaricata: usa il riquadro 1b della Web UI per scaricarla,"
    Write-Host "poi rilancia questo comando."
    exit 1
}

Write-Host ""
Write-Host "Salvato ($($esito.status))." -ForegroundColor Green

# Riepilogo del dominio, per sapere subito quante ne restano.
try {
    $dominio = ([uri]$Url).Host
    $gold = (Invoke-RestMethod -Uri "$ApiBase/gold_standard_urls?domain=$([uri]::EscapeDataString($dominio))").gold_standard_urls
    Write-Host "$dominio : $($gold.Count) entry con gold_text (ne servono 10)."
} catch {
    # Il riepilogo e' un di piu': se il dominio non e' fra quelli supportati
    # non e' un errore del salvataggio, che e' gia' andato a buon fine.
}
