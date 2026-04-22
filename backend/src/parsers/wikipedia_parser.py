import requests
from bs4 import BeautifulSoup

def parse_wikipedia(url: str):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    # 1. Scarica la pagina
    response = requests.get(url, headers=headers)
    html_content = response.text

    # 2. Analizza l'HTML
    soup = BeautifulSoup(html_content, 'html.parser')

    # 3. Trova il titolo
    title_tag = soup.find('h1', id='firstHeading')
    title = title_tag.text.strip() if title_tag else "Titolo non trovato"

    # 4. Trova il contenitore universale del testo di Wikipedia
    content_div = soup.find('div', class_='mw-parser-output')
    
    parsed_text = ""
    if content_div:
        # PULIZIA DEL RUMORE (fondamentale per il progetto!)
        # Rimuove tabelle laterali (sinottico per l'Italia, infobox per l'Inglese) e menu di navigazione
        for box in content_div.find_all(['table', 'div'], class_=['infobox', 'sinottico', 'navbox', 'metadata']):
            box.decompose()
            
        # Rimuove i numeretti delle note (es. [1]) e i tastini "modifica"
        for ref in content_div.find_all(['sup', 'span'], class_=['reference', 'mw-editsection']):
            ref.decompose()
            
        # 5. Estrai tutti i paragrafi puliti
        paragraphs = content_div.find_all('p')
        
        # Filtriamo i paragrafi vuoti e li uniamo con due "a capo" per formare il testo finale
        testi_validi = [p.text.strip() for p in paragraphs if p.text.strip() != ""]
        parsed_text = "\n\n".join(testi_validi)

    return {
        "url": url,
        "domain": "wikipedia.org",
        "title": title,
        "htmltext": html_content,
        "parsedtext": parsed_text
    }
