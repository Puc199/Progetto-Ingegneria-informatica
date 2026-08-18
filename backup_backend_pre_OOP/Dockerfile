FROM python:3.11-slim

WORKDIR /app

# Dipendenze di sistema:
#   build-essential + libmariadb-dev  servono a compilare mariadb-connector,
#                                     che e' un'estensione C e non una ruota pura
#   le altre librerie sono quelle di cui Chromium ha bisogno per partire in
#   modalita' headless, richiesto da Crawl4AI
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libmariadb-dev \
        pkg-config \
        wget \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Scarica Chromium e le sue dipendenze di sistema. Senza questo passaggio
# Crawl4AI e' installato ma non ha un browser da avviare: ogni download
# fallirebbe in silenzio ripiegando sul fetch HTTP semplice, perdendo tutto
# cio' che il sito costruisce in JavaScript.
RUN playwright install --with-deps chromium

COPY backend/src ./src
COPY domains.json ./domains.json
COPY gs_data ./gs_data

EXPOSE 8003

CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8003"]
