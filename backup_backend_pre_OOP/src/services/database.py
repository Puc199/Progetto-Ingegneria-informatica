"""
Accesso a MariaDB con MariaDB Connector/Python.

Questo modulo si occupa solo di connettersi e di eseguire query: le query
specifiche del progetto stanno in repository.py. La separazione serve a
tenere in un posto solo le due cose che vanno fatte bene una volta e poi
riusate ovunque: la gestione del pool di connessioni e l'uso delle query
parametrizzate.

Query parametrizzate, sempre
----------------------------
Ogni funzione qui accetta la query con i segnaposto '?' e i valori come
tupla separata. Il driver sostituisce i segnaposto trattando i valori come
dati puri, mai come codice SQL. Costruire le query con le f-string
esporrebbe il sistema alla SQL injection: gli URL arrivano dal corpo delle
richieste HTTP, quindi sono input non fidato a tutti gli effetti.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Sequence

import mariadb

logger = logging.getLogger(__name__)

DB_HOST = os.getenv("DB_HOST", "mariadb")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "lab_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "lab_password")
DB_NAME = os.getenv("DB_NAME", "parsing_db")

POOL_NAME = "lab_pool"
POOL_SIZE = 5

_pool: Optional[mariadb.ConnectionPool] = None


class DatabaseError(RuntimeError):
    """Errore di accesso al database, gia' tradotto per i livelli superiori."""


def _pool_config() -> dict:
    return {
        "host": DB_HOST,
        "port": DB_PORT,
        "user": DB_USER,
        "password": DB_PASSWORD,
        "database": DB_NAME,
        "autocommit": False,
    }


def init_pool(retries: int = 30, delay: float = 2.0) -> None:
    """
    Crea il pool di connessioni, riprovando finche' MariaDB non e' pronto.

    Il compose usa gia' un healthcheck, ma il retry resta: se il database
    viene riavviato mentre il backend e' in piedi, il primo tentativo
    fallisce e senza questo il servizio resterebbe rotto.

    Raises:
        DatabaseError: se il database non risponde entro i tentativi previsti.
    """
    global _pool

    if _pool is not None:
        return

    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            _pool = mariadb.ConnectionPool(pool_name=POOL_NAME,
                                           pool_size=POOL_SIZE,
                                           **_pool_config())
            logger.info("Connesso a MariaDB su %s:%s/%s", DB_HOST, DB_PORT, DB_NAME)
            return
        except mariadb.Error as exc:
            last_error = exc
            logger.warning("MariaDB non ancora pronto (tentativo %d/%d): %s",
                           attempt, retries, exc)
            time.sleep(delay)

    raise DatabaseError(f"Impossibile connettersi a MariaDB: {last_error}")


@contextmanager
def get_connection() -> Iterator[mariadb.Connection]:
    """
    Fornisce una connessione dal pool e la restituisce a fine blocco.

    In caso di eccezione la transazione viene annullata: senza rollback la
    connessione tornerebbe nel pool con una transazione aperta e il problema
    si manifesterebbe sulla richiesta successiva, altrove.
    """
    if _pool is None:
        init_pool()

    connection = None
    try:
        connection = _pool.get_connection()
        yield connection
    except mariadb.Error as exc:
        if connection is not None:
            try:
                connection.rollback()
            except mariadb.Error:
                pass
        raise DatabaseError(str(exc)) from exc
    finally:
        if connection is not None:
            connection.close()      # con il pool, close() restituisce la connessione


def fetch_all(query: str, params: Sequence[Any] = ()) -> list[dict]:
    """Esegue una SELECT e restituisce le righe come dizionari."""
    with get_connection() as connection:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(query, tuple(params))
            return list(cursor.fetchall())
        finally:
            cursor.close()


def fetch_one(query: str, params: Sequence[Any] = ()) -> Optional[dict]:
    """Esegue una SELECT e restituisce la prima riga, o None."""
    rows = fetch_all(query, params)
    return rows[0] if rows else None


def execute(query: str, params: Sequence[Any] = ()) -> int:
    """
    Esegue una INSERT, UPDATE o DELETE e rende la modifica permanente.

    Returns:
        Numero di righe interessate.
    """
    with get_connection() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(query, tuple(params))
            connection.commit()
            return cursor.rowcount
        finally:
            cursor.close()


def execute_many(query: str, rows: Sequence[Sequence[Any]]) -> int:
    """
    Esegue la stessa query su piu' righe in una sola transazione.

    Usato dal caricamento iniziale: un commit per ogni entry del Gold
    Standard renderebbe l'avvio inutilmente lento.
    """
    if not rows:
        return 0

    with get_connection() as connection:
        cursor = connection.cursor()
        try:
            cursor.executemany(query, [tuple(row) for row in rows])
            connection.commit()
            return cursor.rowcount
        finally:
            cursor.close()


def is_available() -> bool:
    """
    Vero se il database risponde. Usato da GET /status, che non deve
    sollevare eccezioni ma riportare lo stato dentro il JSON.
    """
    try:
        with get_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchall()
                return True
            finally:
                cursor.close()
    except Exception:
        return False


def table_schema() -> dict[str, dict[str, str]]:
    """
    Schema del database nel formato richiesto da GET /db_schema.

    Legge information_schema invece di ricopiare a mano lo schema: cosi' la
    risposta non puo' divergere dal database reale quando lo schema cambia.
    """
    columns = fetch_all(
        """
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_KEY
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = ?
        ORDER BY TABLE_NAME, ORDINAL_POSITION
        """,
        (DB_NAME,),
    )

    foreign_keys = fetch_all(
        """
        SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = ? AND REFERENCED_TABLE_NAME IS NOT NULL
        """,
        (DB_NAME,),
    )

    fk_map = {
        (row["TABLE_NAME"], row["COLUMN_NAME"]):
            f"FK({row['REFERENCED_TABLE_NAME']}.{row['REFERENCED_COLUMN_NAME']})"
        for row in foreign_keys
    }

    schema: dict[str, dict[str, str]] = {}
    for row in columns:
        table = row["TABLE_NAME"]
        column = row["COLUMN_NAME"]

        parts = [row["COLUMN_TYPE"]]
        if row["COLUMN_KEY"] == "PRI":
            parts.append("PK")
        reference = fk_map.get((table, column))
        if reference:
            parts.append(reference)

        schema.setdefault(table, {})[column] = ", ".join(parts)

    return schema
