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
    ensure_schema(conn, apply_layout=False)


def ensure_schema(conn, *, apply_layout=True):
    exists = conn.execute("SELECT to_regclass('anivrum.schema_version')").fetchone()[0]
    if not exists:
        conn.execute("CREATE SCHEMA IF NOT EXISTS anivrum")
        conn.execute(Path(__file__).with_name("postgres_v4.sql").read_text(encoding="utf-8"))
    check_version(conn)
    if not catalog_layout_ready(conn):
        if exists and not apply_layout:
            raise RuntimeError("Avval database.migrate_catalog_layout migratsiyasini bajaring.")
        conn.execute(Path(__file__).with_name("catalog_layout.sql").read_text(encoding="utf-8"))
        if not catalog_layout_ready(conn):
            raise RuntimeError("Katalog migratsiyasi to‘liq bajarilmadi.")


def catalog_layout_ready(conn):
    columns = {
        (table, column): (data_type, nullable)
        for table, column, data_type, nullable in conn.execute("""
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns WHERE table_schema='anivrum'
              AND table_name IN ('seasons','episodes','standalone_videos')
        """)
    }
    expected = {
        ("seasons", "sort_order"): ("bigint", "YES"),
        ("episodes", "sort_order"): ("bigint", "YES"),
        ("standalone_videos", "sort_order"): ("bigint", "YES"),
        ("standalone_videos", "season_id"): ("bigint", "YES"),
        ("standalone_videos", "poster_file_id"): ("text", "YES"),
    }
    index_ready, foreign_key_ready = conn.execute("""
        SELECT EXISTS (
            SELECT 1 FROM pg_index i JOIN pg_attribute a
              ON a.attrelid=i.indrelid AND a.attnum=i.indkey[0]
            WHERE i.indexrelid=to_regclass('anivrum.idx_standalone_season')
              AND i.indrelid=to_regclass('anivrum.standalone_videos')
              AND i.indisvalid AND i.indisready AND i.indnatts=1
              AND i.indpred IS NULL AND a.attname='season_id'
        ), EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid=to_regclass('anivrum.standalone_videos')
              AND confrelid=to_regclass('anivrum.seasons')
              AND contype='f' AND confdeltype='n' AND convalidated
              AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (season_id) REFERENCES %seasons(id) ON DELETE SET NULL'
        )
    """).fetchone()
    found = expected.keys() & columns.keys()
    if not found and not index_ready and not foreign_key_ready:
        return False
    if (all(columns.get(column) == definition for column, definition in expected.items())
            and index_ready and foreign_key_ready):
        return True
    raise RuntimeError("Katalog sxemasi qisman yoki boshqa shaklda o‘zgartirilgan.")


def check_version(conn):
    version = conn.execute("SELECT version FROM schema_version WHERE singleton=1").fetchone()
    if not version or version[0] != 4:
        raise RuntimeError("PostgreSQL sxemasi versiyasi mos kelmaydi.")
