"""Opt-in snapshots kept apart from legacy statistics and the catalog."""

from datetime import UTC, datetime, timedelta

from database import db, postgres

RETENTION = timedelta(days=30)


def migrate():
    with db.connection() as conn:
        if db.database_url():
            postgres.lock_schema(conn)
        migrate_schema(conn)


def migrate_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS user_activity_snapshot (
        user_id BIGINT PRIMARY KEY NOT NULL,
        consented_at BIGINT NOT NULL,
        recorded_at BIGINT,
        username TEXT,
        section TEXT,
        content_kind TEXT,
        content_id BIGINT,
        content_at BIGINT,
        expires_at BIGINT NOT NULL
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_activity_snapshot_username
        ON user_activity_snapshot (username)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_activity_snapshot_expiry
        ON user_activity_snapshot (expires_at)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_activity_snapshot_recent
        ON user_activity_snapshot (recorded_at DESC, user_id)""")


def timestamps(now=None):
    now = now or datetime.now(UTC)
    return int(now.timestamp()), int((now + RETENTION).timestamp())


def allow(user_id, now=None):
    at, expires = timestamps(now)
    with db.connection() as conn:
        conn.execute("""INSERT INTO user_activity_snapshot(user_id, consented_at, expires_at)
            VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET
            consented_at=excluded.consented_at, expires_at=excluded.expires_at,
            recorded_at=NULL, username=NULL, section=NULL, content_kind=NULL, content_id=NULL, content_at=NULL
            WHERE user_activity_snapshot.expires_at <= excluded.consented_at""", (user_id, at, expires))


def allowed(user_id):
    at, _ = timestamps()
    with db.connection() as conn:
        return conn.execute("""SELECT 1 FROM user_activity_snapshot
            WHERE user_id=? AND expires_at>?""", (user_id, at)).fetchone() is not None


def record(user_id, username, section, kind=None, content_id=None, now=None):
    at, expires = timestamps(now)
    with db.connection() as conn:
        conn.execute("""UPDATE user_activity_snapshot SET
            username=?, recorded_at=?, section=COALESCE(?, section),
            content_kind=COALESCE(?, content_kind), content_id=COALESCE(?, content_id),
            content_at=COALESCE(?, content_at), expires_at=?
            WHERE user_id=? AND expires_at>? AND consented_at<=?
              AND (recorded_at IS NULL OR recorded_at<=?)""",
                     (username.lower() if username else None, at, section, kind, content_id, at if kind else None,
                      expires, user_id, at, at, at))


def delete(user_id):
    with db.connection() as conn:
        conn.execute("DELETE FROM user_activity_snapshot WHERE user_id=?", (user_id,))


def prune(now=None):
    at, expires = timestamps(now)
    with db.connection() as conn:
        removed = conn.execute("DELETE FROM user_activity_snapshot WHERE expires_at<=?", (at,)).rowcount
        conn.execute("""UPDATE user_activity_snapshot SET content_kind=NULL, content_id=NULL, content_at=NULL
            WHERE content_at<=?""", (2 * at - expires,))
        return removed


def find(*, user_id=None, username=None, page=0, limit=11, now=None):
    at, expires = timestamps(now)
    query = """SELECT user_id, username, recorded_at, section,
        CASE WHEN content_at>? THEN content_kind END AS content_kind,
        CASE WHEN content_at>? THEN content_id END AS content_id
        FROM user_activity_snapshot WHERE expires_at>? AND recorded_at IS NOT NULL"""
    cutoff = 2 * at - expires
    params = [cutoff, cutoff, at]
    if user_id is not None:
        query += " AND user_id=?"
        params.append(user_id)
    if username is not None:
        query += " AND username=?"
        params.append(username.lower())
    with db.connection() as conn:
        return conn.execute(query + " ORDER BY recorded_at DESC, user_id LIMIT ? OFFSET ?",
                            (*params, limit, page * (limit - 1))).fetchall()


def describe(kind, content_id):
    queries = {
        "anime": "SELECT title FROM animes WHERE id=?",
        "season": """SELECT a.title,s.season_number FROM seasons s
            JOIN animes a ON a.id=s.anime_id WHERE s.id=?""",
        "episode": """SELECT a.title,s.season_number,e.episode_number FROM episodes e
            JOIN seasons s ON s.id=e.season_id JOIN animes a ON a.id=s.anime_id WHERE e.id=?""",
        "film": """SELECT a.title,v.title FROM standalone_videos v
            JOIN animes a ON a.id=v.anime_id WHERE v.id=? AND v.kind='film'""",
        "ova": """SELECT a.title,v.title FROM standalone_videos v
            JOIN animes a ON a.id=v.anime_id WHERE v.id=? AND v.kind='ova'""",
    }
    query = queries.get(kind)
    if not query or content_id is None:
        return None
    with db.connection() as conn:
        row = conn.execute(query, (content_id,)).fetchone()
    if not row:
        return None
    if kind in {"film", "ova"}:
        return f"{row[0]} · {'Film' if kind == 'film' else 'OVA'} — {row[1]}"
    return " · ".join((row[0], *(f"{value}-{suffix}" for value, suffix in zip(row[1:], ("fasl", "qism")))))
