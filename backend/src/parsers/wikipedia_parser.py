import requests
from bs4 import BeautifulSoup
import re

def parse_wikipedia(url: str) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"error": f"URL non raggiungibile: {e}"}

    html_content = response.text
    soup = BeautifulSoup(html_content, 'html.parser')

    title_tag = soup.find('h1', id='firstHeading')
    title = title_tag.text.strip() if title_tag else "Titolo non trovato"

    content_div = soup.find('div', class_='mw-parser-output')
    parsed_text = ""

    if content_div:
        # Rimuovi rumore
        for box in content_div.find_all(['table', 'div'], class_=[
            'infobox', 'sinottico', 'navbox', 'metadata',
            'mw-references-wrap', 'reflist', 'sidebar'
        ]):
            box.decompose()
        for ref in content_div.find_all(['sup', 'span'], class_=['reference', 'mw-editsection']):
            ref.decompose()

        # Sezioni finali da escludere
        STOP_SECTIONS = {'note', 'references', 'bibliography', 'bibliography',
                         'see also', 'voci correlate', 'bibliografia',
                         'collegamenti esterni', 'external links'}

        lines = []
        stop = False
        for tag in content_div.find_all(['h2', 'h3', 'h4', 'p', 'ul', 'ol']):
            if tag.name in ['h2', 'h3', 'h4']:
                heading_text = tag.get_text().strip().lower()
                # Rimuove "[modifica | modifica wikitesto]"
                heading_text = re.sub(r'\[.*?\]', '', heading_text).strip()
                if heading_text in STOP_SECTIONS:
                    stop = True
                if stop:
                    continue
                level = int(tag.name[1])
                lines.append(f"\n{'#' * level} {tag.get_text(separator=' ').strip()}\n")
            elif tag.name == 'p' and not stop:
                text = tag.get_text().strip()
                if text:
                    lines.append(text)
            elif tag.name in ['ul', 'ol'] and not stop:
                for li in tag.find_all('li', recursive=False):
                    lines.append(f"- {li.get_text().strip()}")

        parsed_text = "\n\n".join(lines)

    return {
        "url": url,
        "domain": "wikipedia.org",
        "title": title,
        "htmltext": html_content,
        "parsedtext": parsed_text
    }