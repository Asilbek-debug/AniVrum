"""SQLite bazasining izchil zaxira nusxasini yaratish."""

import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from database.db import DB_PATH


def backup(destination):
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = destination / f"anivrum-{timestamp}.db"
    temporary = target.with_suffix(".partial")
    temporary.touch(mode=0o600, exist_ok=False)
    try:
        with (
            closing(sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(temporary)) as copy,
        ):
            source.backup(copy)
            if copy.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise sqlite3.DatabaseError("Zaxira nusxasi yaxlitlik tekshiruvidan o'tmadi.")
        temporary.rename(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Zaxira nusxalari papkasi")
    args = parser.parse_args()
    print(backup(args.directory))
