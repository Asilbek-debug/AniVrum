"""PostgreSQL connections for the shared repository queries."""

from contextlib import contextmanager
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None


class Row(tuple):
    def __new__(cls, columns, values):
        row = super().__new__(cls, values)
        row.columns = columns
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            key = self.columns.index(key)
        return super().__getitem__(key)

    def keys(self):
        return self.columns


def row_factory(cursor):
    columns = tuple(column.name for column in cursor.description or ())
    return lambda values: Row(columns, values)


def parameterized(query):
    # Shared repository statements use qmarks only for bind parameters.
    return query.replace("%", "%%").replace("?", "%s")


if psycopg is not None:
    class Cursor(psycopg.Cursor):
        def execute(self, query, params=None, **kwargs):
            return super().execute(parameterized(query) if params is not None else query, params, **kwargs)

        def executemany(self, query, params_seq, **kwargs):
            return super().executemany(parameterized(query), params_seq, **kwargs)


@contextmanager
def connection(url):
    if psycopg is None:
        raise RuntimeError("PostgreSQL uchun psycopg[binary] paketini o‘rnating.")
    with psycopg.connect(url, connect_timeout=5, row_factory=row_factory, cursor_factory=Cursor,
                         application_name="AniVrum") as conn:
        conn.execute("SET LOCAL search_path TO anivrum, pg_catalog")
        yield conn


def lock_schema(conn):
    conn.execute("SELECT pg_advisory_xact_lock(201341, 4)")


def migrate(conn):
    lock_schema(conn)
    ensure_schema(conn)


def ensure_schema(conn):
    exists = conn.execute("SELECT to_regclass('anivrum.schema_version')").fetchone()[0]
    if not exists:
        conn.execute("CREATE SCHEMA IF NOT EXISTS anivrum")
        conn.execute(Path(__file__).with_name("postgres_v4.sql").read_text(encoding="utf-8"))
    check_version(conn)


def check_version(conn):
    version = conn.execute("SELECT version FROM schema_version WHERE singleton=1").fetchone()
    if not version or version[0] != 4:
        raise RuntimeError("PostgreSQL sxemasi versiyasi mos kelmaydi.")
