import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(
    os.environ.get("TALENTMATCH_DB", Path(__file__).resolve().parent / "talentmatch.sqlite3")
)
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


@contextmanager
def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()
