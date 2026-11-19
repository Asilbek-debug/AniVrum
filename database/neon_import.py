"""Use the verified AniVrum snapshot for the interactive Neon import."""

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from psycopg.conninfo import make_conninfo

from database import import_postgres, neon_preflight

BACKUP_NAME = "anivrum-20261119T223530827917Z.db"
BACKUP = Path(__file__).resolve().parent.parent / "backups" / BACKUP_NAME
SHA256 = "31241eb0c2eb960887a2da3f9534d35513411e583f62554b60e35cc308e86567"
EXPECTED = {"animes": 3, "seasons": 4, "episodes": 39, "content_codes": 4, "anime_views": 37}
EXPECTED_VIDEO_IDS = 39


def validate_backup(path):
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SHA256:
            raise import_postgres.ImportCheckError("Zaxira fayli tasdiqlangan SHA-256 qiymatiga mos emas.")
    with import_postgres.snapshot(path) as (source, _):
        result = import_postgres.counts(source)
        videos = source.execute(
            "SELECT COUNT(*) FROM episodes WHERE COALESCE(video_file_id, '') <> ''"
        ).fetchone()[0]
        if any(result[table] != count for table, count in EXPECTED.items()) or videos != EXPECTED_VIDEO_IDS:
            raise import_postgres.ImportCheckError("Zaxiradagi yozuvlar kutilgan sonlarga mos emas.")


def run_import(source, options):
    os.environ["ANIVRUM_IMPORT_DATABASE_URL"] = make_conninfo(**options)
    try:
        try:
            import_postgres.main(["--source", str(source), "--apply"])
        except (SystemExit, Exception):
            print("Import tasdiqlanmadi. Qayta urinishdan oldin Neon holatini tekshiring.", file=sys.stderr)
            return 1
        try:
            import_postgres.main(["--source", str(source), "--verify"])
        except (SystemExit, Exception):
            print("Import commit qilindi, ammo mustaqil tekshiruv muvaffaqiyatsiz. Qayta import qilmang.",
                  file=sys.stderr)
            return 3
        print(f"Import muvaffaqiyatli. Barcha jadvallar mos va {EXPECTED_VIDEO_IDS} ta video file_id saqlandi.")
        return 0
    finally:
        os.environ.pop("ANIVRUM_IMPORT_DATABASE_URL", None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "confirmed-import"))
    args = parser.parse_args(argv)
    url = os.environ.pop("ANIVRUM_IMPORT_DATABASE_URL", "").strip()
    try:
        options = neon_preflight.connection_options(url)
        if neon_preflight.check(url):
            print("Neon bazasida foydalanuvchi obyektlari bor. Import bloklandi.", file=sys.stderr)
            return 2
        if args.action == "check":
            validate_backup(BACKUP)
            print("TLS tasdiqlandi. Neon bo‘sh. SQLite zaxirasi integrity_check: ok.")
            return 0
        with TemporaryDirectory(prefix="anivrum-approved-import-") as directory:
            source = Path(directory) / BACKUP_NAME
            shutil.copyfile(BACKUP, source)
            validate_backup(source)
            return run_import(source, options)
    except (neon_preflight.PreflightError, import_postgres.ImportCheckError) as error:
        print(f"Amal to‘xtatildi. {error}", file=sys.stderr)
    except Exception:
        print("Ulanish, TLS yoki zaxira tekshiruvi yakunlanmadi. Qayta urinishdan oldin Neon holatini tekshiring.",
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
