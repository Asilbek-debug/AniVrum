"""Inspect, import, or compare a SQLite snapshot with an AniVrum PostgreSQL database."""

import argparse
import os
import sqlite3
from contextlib import closing, contextmanager
from itertools import zip_longest
from pathlib import Path
from tempfile import TemporaryDirectory

from database import catalog, db, postgres

IDENTITIES = (
    "animes", "seasons", "episodes", "favorites", "anime_views",
    "standalone_videos", "anime_news", "anime_comments",
)
ORDER_KEYS = {
    **{table: "id" for table in IDENTITIES},
    "announcements": "anime_id",
    "content_codes": "code",
    "bot_users": "user_id",
    "bot_metrics": "day, kind, subject",
}
PG_ORDER_KEYS = {
    "content_codes": 'code COLLATE "C"',
    "bot_metrics": 'day COLLATE "C", kind COLLATE "C", subject',
}


class ImportCheckError(RuntimeError):
    pass


@contextmanager
def snapshot(path):
    """Take a consistent snapshot including committed WAL data, then upgrade only that copy."""
    with TemporaryDirectory(prefix="anivrum-import-") as directory:
        scratch = Path(directory) / "snapshot.db"
        with closing(sqlite3.connect(scratch)) as copy, copy:
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                source.backup(copy)
            version = copy.execute("PRAGMA user_version").fetchone()[0]
            if version not in (3, 4):
                raise ImportCheckError("SQLite manbasi v3 yoki v4 bo‘lishi kerak.")
            if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ImportCheckError("SQLite manbasi integrity_check tekshiruvidan o‘tmadi.")
            catalog.migrate_sqlite(copy)
            if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ImportCheckError("Migratsiya qilingan nusxa yaxlitligi buzilgan.")
            tables = {row[0] for row in copy.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
            if tables != set(ORDER_KEYS):
                raise ImportCheckError("SQLite jadvallari kutilgan v4 sxemasiga mos emas.")
            yield copy, version


def columns(source, table):
    return tuple(row[1] for row in source.execute(f'PRAGMA table_info("{table}")'))


def projection(source, table):
    return ", ".join('"' + name.replace('"', '""') + '"' for name in columns(source, table))


def counts(source):
    return {table: source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ORDER_KEYS}


def verify(source, target):
    postgres.check_version(target)
    source_counts = counts(source)
    if source_counts != counts(target):
        raise ImportCheckError("SQLite va PostgreSQL yozuvlar soni mos emas.")
    missing = object()
    for table, ordering in ORDER_KEYS.items():
        fields = projection(source, table)
        original = source.execute(f"SELECT {fields} FROM {table} ORDER BY {ordering}")
        copied = target.execute(f"SELECT {fields} FROM {table} ORDER BY {PG_ORDER_KEYS.get(table, ordering)}")
        for left, right in zip_longest(original, copied, fillvalue=missing):
            if left is missing or right is missing or left != tuple(right):
                raise ImportCheckError(f"{table} jadvalidagi qiymatlar mos emas.")
    return source_counts


def transfer(source, target):
    postgres.lock_schema(target)
    postgres.ensure_schema(target)
    db.lock_writes(target, *ORDER_KEYS)
    if any(counts(target).values()):
        raise ImportCheckError("PostgreSQL manzili bo‘sh emas. Mavjud yozuvlar saqlanadi.")
    for table in ORDER_KEYS:
        fields = projection(source, table)
        placeholders = ", ".join("?" for _ in columns(source, table))
        records = source.execute(f"SELECT {fields} FROM {table}")
        target.cursor().executemany(f"INSERT INTO {table} ({fields}) VALUES ({placeholders})", records)
    copied = verify(source, target)
    high_water_marks = dict(source.execute("SELECT name, seq FROM sqlite_sequence"))
    for table in IDENTITIES:
        max_id = source.execute(f"SELECT COALESCE(MAX(id),0) FROM {table}").fetchone()[0]
        sequence = high_water_marks.get(table, 0)
        if not isinstance(sequence, int):
            raise ImportCheckError(f"{table} jadvalidagi SQLite ketma-ketligi yaroqsiz.")
        next_id = max(0, max_id, sequence) + 1
        if next_id >= 2**63:
            raise ImportCheckError(f"{table} jadvali uchun keyingi ID mavjud emas.")
        target.execute(f"ALTER TABLE {table} ALTER COLUMN id RESTART WITH {next_id}")
    return copied


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="SQLite snapshot path")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Import into an empty PostgreSQL schema")
    mode.add_argument("--verify", action="store_true", help="Read-only comparison against PostgreSQL")
    args = parser.parse_args(argv)
    url = os.getenv("ANIVRUM_IMPORT_DATABASE_URL", "").strip()
    if (args.apply or args.verify) and not url:
        parser.error("ANIVRUM_IMPORT_DATABASE_URL kerak.")
    try:
        with snapshot(args.source) as (source, version):
            if args.apply or args.verify:
                with postgres.connection(url) as target:
                    if args.apply:
                        result = transfer(source, target)
                    else:
                        target.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                        result = verify(source, target)
            else:
                result = counts(source)
        print(f"SQLite v{version}; tekshirilgan sxema v4")
        for table, count in result.items():
            print(f"{table}: {count}")
    except ImportCheckError as error:
        parser.exit(1, f"{error}\n")
    except (*db.DATABASE_ERRORS, OSError, RuntimeError) as error:
        # Driver errors can contain connection details or personal data.
        parser.exit(1, f"Amal bajarilmadi ({type(error).__name__}).\n")


if __name__ == "__main__":
    main()
