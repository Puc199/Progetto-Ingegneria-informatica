-- Schema del database del progetto.
--
-- Questo file viene montato in /docker-entrypoint-initdb.d/ del container
-- MariaDB ed eseguito automaticamente alla prima creazione del data
-- directory, prima che qualunque altro servizio possa collegarsi.
-- Qui c'e' solo DDL: i dati (Gold Standard e HTML) vengono caricati dal
-- backend con MariaDB Connector/Python, cosi' i file JSON restano l'unica
-- fonte di verita' e non vanno duplicati dentro un dump SQL da megabyte.

CREATE DATABASE IF NOT EXISTS parsing_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE parsing_db;


-- ---------------------------------------------------------------------------
-- web_resources: le pagine scaricate, con l'HTML grezzo.
-- Nome e colonne sono fissati dalla consegna: i test automatici scrivono
-- direttamente in questa tabella per forzare l'uso dell'HTML locale.
--
-- Nota su url VARCHAR(2048) come PRIMARY KEY.
-- InnoDB limita una chiave a 3072 byte. In utf8mb4 un carattere occupa fino
-- a 4 byte, quindi 2048 caratteri varrebbero 8192 byte e la CREATE TABLE
-- fallirebbe. Gli URL sono ASCII per definizione (RFC 3986: i caratteri
-- fuori set vanno percent-encoded), quindi si dichiara la colonna in ascii:
-- 2048 byte, sotto il limite, e la lunghezza richiesta dalla specifica resta
-- esattamente quella. La collation ascii_bin rende inoltre il confronto
-- case-sensitive, che e' il comportamento giusto per un URL.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS web_resources (
    url        VARCHAR(2048) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    domain     VARCHAR(255)  NOT NULL,
    title      VARCHAR(2048) NOT NULL DEFAULT '',
    html_text  LONGTEXT      NOT NULL,
    created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (url),
    INDEX idx_web_resources_domain (domain)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC;


-- ---------------------------------------------------------------------------
-- gold_standard: il testo di riferimento estratto a mano.
-- Relazione uno-a-uno con web_resources, come richiesto: la stessa colonna
-- e' insieme chiave primaria (quindi unica) e chiave esterna.
-- ON DELETE CASCADE implementa il requisito di DELETE /web_resource, che
-- deve rimuovere a cascata il gold standard associato.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold_standard (
    url        VARCHAR(2048) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    gold_text  LONGTEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (url),
    CONSTRAINT fk_gold_standard_web_resource
        FOREIGN KEY (url) REFERENCES web_resources (url)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC;


-- ---------------------------------------------------------------------------
-- parsed_documents: l'output del parser per una risorsa.
-- Tabella libera. Serve a /db_stats, che per specifica deve leggere dati
-- gia' calcolati invece di rifare il parsing a ogni chiamata.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parsed_documents (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    url         VARCHAR(2048) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    parser_name VARCHAR(128) NOT NULL,
    parsed_text LONGTEXT     NOT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_parsed_documents_url (url),
    CONSTRAINT fk_parsed_documents_web_resource
        FOREIGN KEY (url) REFERENCES web_resources (url)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC;


-- ---------------------------------------------------------------------------
-- evaluations: i risultati delle metriche automatiche.
-- Una riga per (url, metrica): la tabella non va modificata per aggiungere
-- una metrica nuova, basta inserire righe con un metric_name diverso.
-- precision/recall/f1 servono a token_level_eval, score alle metriche che
-- producono un valore singolo.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evaluations (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    url         VARCHAR(2048) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    metric_name VARCHAR(64)  NOT NULL,
    precision_v DECIMAL(6,5) NULL,
    recall_v    DECIMAL(6,5) NULL,
    f1_v        DECIMAL(6,5) NULL,
    score_v     DECIMAL(6,5) NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_evaluations_url_metric (url, metric_name),
    CONSTRAINT fk_evaluations_web_resource
        FOREIGN KEY (url) REFERENCES web_resources (url)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC;


-- ---------------------------------------------------------------------------
-- judgements: i giudizi dell'LLM.
-- model_name fa parte della chiave: cosi' si possono confrontare piu'
-- modelli sulla stessa pagina, che e' quello che serve per motivare nel
-- report la scelta del judge definitivo.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS judgements (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    url            VARCHAR(2048) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    model_name     VARCHAR(128) NOT NULL,
    judge_score    TINYINT      NOT NULL,
    judge_feedback TEXT         NOT NULL,
    parse_ok       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_judgements_url_model (url, model_name),
    CONSTRAINT chk_judge_score CHECK (judge_score BETWEEN 1 AND 5),
    CONSTRAINT fk_judgements_web_resource
        FOREIGN KEY (url) REFERENCES web_resources (url)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC;


-- L'utente applicativo e' creato dalle variabili d'ambiente del container
-- (MARIADB_USER / MARIADB_PASSWORD) sul solo database MARIADB_DATABASE.
-- Qui si estendono i privilegi al database creato sopra, perche' il backend
-- lavora su parsing_db e non sul database di default.
GRANT ALL PRIVILEGES ON parsing_db.* TO 'lab_user'@'%';
FLUSH PRIVILEGES;
