"""Apply the additive AniVrum V5 catalog layout migration to an existing PostgreSQL database."""

import argparse
import os

from database import db, postgres
from database.neon_preflight import connection_options


def apply(url, *, check=False):
    with postgres.connection(url) as conn:
        if check:
            conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SET LOCAL statement_timeout = '60s'")
        if not check:
            postgres.lock_schema(conn)
        postgres.check_version(conn)
        conn.execute("SELECT id FROM anivrum.animes LIMIT 0")
        conn.execute("SELECT id, anime_id FROM anivrum.seasons LIMIT 0")
        conn.execute("SELECT id, season_id, video_file_id FROM anivrum.episodes LIMIT 0")
        conn.execute("SELECT id, anime_id, file_id FROM anivrum.standalone_videos LIMIT 0")
        conn.execute("SELECT user_id FROM anivrum.bot_users LIMIT 0")
        ready = postgres.catalog_layout_ready(conn)
        if not ready:
            owns_tables = conn.execute("""
                SELECT COUNT(*)=3 AND bool_and(pg_has_role(c.relowner,'USAGE'))
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='anivrum' AND c.relkind IN ('r','p')
                  AND c.relname IN ('seasons','episodes','standalone_videos')
            """).fetchone()[0]
            if not owns_tables:
                raise RuntimeError("Migratsiya jadvallari egasi huquqi topilmadi.")
            if not check:
                postgres.ensure_schema(conn)
        return ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("ANIVRUM_PRODUCTION_NEON_URL", "").strip()
    endpoint = os.environ.get("ANIVRUM_PRODUCTION_NEON_ENDPOINT", "").strip().lower()
    try:
        options = connection_options(url)
        if not endpoint or options["host"].lower() != endpoint:
            raise RuntimeError("Production endpoint mos kelmadi.")
        ready = apply(postgres.psycopg.conninfo.make_conninfo(**options), check=args.check)
    except (*db.DATABASE_ERRORS, RuntimeError, ValueError) as error:
        parser.exit(1, f"Neon tekshiruvi yoki migratsiyasi bajarilmadi ({type(error).__name__}).\n")
    if ready:
        print("AniVrum V5 katalog sxemasi tayyor. DDL bajarilmadi.")
    elif args.check:
        print("Neon v4 sxemasi va jadval egaligi tasdiqlandi. V5 migratsiyasi kutilmoqda.")
    else:
        print("AniVrum V5 katalog sxemasi muvaffaqiyatli yangilandi.")


if __name__ == "__main__":
    main()
