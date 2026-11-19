"""Read-only Neon connection and emptiness check."""

import os
import re
import sys

import certifi
import psycopg
from psycopg.conninfo import conninfo_to_dict

RELATION_COUNT = """
    SELECT COUNT(*)
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname <> 'information_schema' AND left(n.nspname, 3) <> 'pg_'
      AND c.relkind IN ('r', 'p', 'f', 'v', 'm', 'S')
"""


class PreflightError(RuntimeError):
    pass


def connection_options(url):
    if not url.startswith(("postgresql://", "postgres://")):
        raise PreflightError("Neon'dan PostgreSQL ulanish URL'ini kiriting.")
    options = conninfo_to_dict(url)
    supported = {"host", "port", "dbname", "user", "password", "sslmode", "channel_binding"}
    if options.keys() - supported:
        raise PreflightError("Neon'dan pooling o‘chirilgan standart URL'ni oling.")
    if options.get("sslmode") != "require":
        raise PreflightError("Neon URL'ida sslmode=require bo‘lishi kerak.")
    host = options.get("host", "").lower()
    if not re.fullmatch(r"ep-[a-z0-9-]+(?:\.[a-z0-9-]+)+\.neon\.tech", host) or "-pooler" in host.split(".")[0]:
        raise PreflightError("Neon'ning bevosita endpointi kerak. Connection pooling'ni o‘chiring.")
    if (options.get("dbname"), options.get("user")) != ("neondb", "neondb_owner"):
        raise PreflightError("Kutilgan baza neondb va rol neondb_owner.")
    if not options.get("password") or options.get("port", "5432") != "5432":
        raise PreflightError("Neon URL tarkibidagi parol va port sozlamasini tekshiring.")
    options.update(sslmode="verify-full", sslrootcert=certifi.where(), channel_binding="require",
                   connect_timeout=10, application_name="AniVrum Neon preflight")
    return options


def check(url):
    with psycopg.connect(**connection_options(url)) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '10s'")
        if not conn.pgconn.ssl_in_use:
            raise PreflightError("TLS tasdiqlanmadi.")
        state = conn.execute(
            "SELECT current_database(), current_user, current_setting('transaction_read_only')"
        ).fetchone()
        if state != ("neondb", "neondb_owner", "on"):
            raise PreflightError("Baza, rol yoki faqat o‘qish rejimi tasdiqlanmadi.")
        return conn.execute(RELATION_COUNT).fetchone()[0]


def main():
    url = os.environ.pop("ANIVRUM_IMPORT_DATABASE_URL", "").strip()
    try:
        count = check(url)
    except PreflightError as error:
        print(f"Tekshiruv rad etildi. {error}", file=sys.stderr)
        return 1
    except Exception:
        # Driver messages can include connection details.
        print("Neon ulanishi yoki TLS tekshiruvi muvaffaqiyatsiz. URL va Neon sozlamalarini tekshiring.",
              file=sys.stderr)
        return 1
    print("Neon ulanishi, TLS sertifikati va faqat o‘qish rejimi tasdiqlandi.")
    if count:
        print(f"Foydalanuvchi sxemalarida {count} ta jadval yoki boshqa relation bor. Import bloklanadi.")
        return 2
    print("Foydalanuvchi jadvallari va boshqa relationlar topilmadi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
