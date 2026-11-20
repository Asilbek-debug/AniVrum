"""AniVrum schema migrations and catalog queries."""

import os
import sqlite3
from datetime import UTC, datetime, timedelta

from database import postgres
from database.db import connection, lock_writes, title_order


def migrate():
    with connection() as conn:
        if isinstance(conn, sqlite3.Connection):
            migrate_sqlite(conn)
        else:
            postgres.migrate(conn)


def migrate_sqlite(conn):
    conn.execute("BEGIN IMMEDIATE")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, 2, 3, 4):
        raise RuntimeError("SQLite sxemasi versiyasi mos kelmaydi.")
    if version == 0:
        _migrate_v1(conn)
    if version < 2:
        conn.execute("ALTER TABLE animes ADD COLUMN country TEXT")
        conn.execute("ALTER TABLE announcements ADD COLUMN poster_file_id TEXT")
    if version < 3:
        # Historical links keep their original target, including deleted anime IDs.
        conn.execute("DROP TRIGGER IF EXISTS retain_content_code_insert")
        conn.execute("DROP TRIGGER IF EXISTS retain_content_code_update")
    if version < 4:
        for statement in (
            "ALTER TABLE animes ADD COLUMN caption_mode TEXT NOT NULL DEFAULT 'auto'",
            "ALTER TABLE animes ADD COLUMN caption_text TEXT",
            "ALTER TABLE animes ADD COLUMN caption_link TEXT",
            "ALTER TABLE announcements ADD COLUMN is_text INTEGER NOT NULL DEFAULT 0",
            """CREATE TABLE standalone_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, anime_id INTEGER NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ('film','ova')), number INTEGER NOT NULL CHECK(number>0),
                title TEXT NOT NULL, description TEXT, file_id TEXT NOT NULL, media_type TEXT NOT NULL,
                release_year INTEGER, country TEXT, genre TEXT,
                UNIQUE(anime_id,kind,number))""",
            """CREATE TABLE anime_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT, anime_id INTEGER REFERENCES animes(id) ON DELETE SET NULL,
                kind TEXT NOT NULL CHECK(kind IN ('anime','film','ova','general')),
                title TEXT NOT NULL, body TEXT NOT NULL, photo TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, published_at TEXT)""",
            """CREATE TABLE anime_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, anime_id INTEGER REFERENCES animes(id) ON DELETE SET NULL,
                anime_title TEXT NOT NULL, anime_code TEXT NOT NULL, user_id INTEGER NOT NULL,
                name TEXT NOT NULL, username TEXT, body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            "CREATE INDEX idx_comment_user_time ON anime_comments(user_id, created_at)",
            "CREATE TABLE bot_users (user_id INTEGER PRIMARY KEY, last_active TEXT NOT NULL)",
            """CREATE TABLE bot_metrics (day TEXT NOT NULL, kind TEXT NOT NULL,
                subject INTEGER NOT NULL, total INTEGER NOT NULL, PRIMARY KEY(day,kind,subject))""",
        ):
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 4")


def _migrate_v1(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='animes'").fetchone():
        conn.execute("""CREATE TABLE animes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL, genre TEXT, description TEXT, release_year INTEGER
        )""")
    for statement in (
        """CREATE TABLE IF NOT EXISTS seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, anime_id INTEGER NOT NULL REFERENCES animes(id),
            season_number INTEGER NOT NULL, UNIQUE(anime_id, season_number))""",
        """CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, season_id INTEGER NOT NULL REFERENCES seasons(id),
            episode_number INTEGER NOT NULL, title TEXT, video_file_id TEXT,
            UNIQUE(season_id, episode_number))""",
        """CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            anime_id INTEGER NOT NULL, UNIQUE(user_id, anime_id))""",
        """CREATE TABLE IF NOT EXISTS anime_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT, anime_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, episode_id INTEGER NOT NULL,
            viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        "ALTER TABLE animes ADD COLUMN kind TEXT NOT NULL DEFAULT 'anime' CHECK(kind IN ('anime','movie'))",
        "ALTER TABLE animes ADD COLUMN poster_file_id TEXT",
        "ALTER TABLE animes ADD COLUMN visible INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE animes ADD COLUMN created_at TEXT",
        "ALTER TABLE animes ADD COLUMN movie_file_id TEXT",
        "ALTER TABLE animes ADD COLUMN movie_media_type TEXT",
        "ALTER TABLE episodes ADD COLUMN media_type TEXT NOT NULL DEFAULT 'video'",
        "ALTER TABLE episodes ADD COLUMN file_unique_id TEXT",
        "ALTER TABLE anime_views ADD COLUMN season_id INTEGER",
        "UPDATE anime_views SET season_id=(SELECT season_id FROM episodes WHERE id=episode_id)",
        """CREATE TABLE announcements (
            anime_id INTEGER PRIMARY KEY, status TEXT NOT NULL,
            chat_id TEXT, message_id INTEGER)""",
        "CREATE TABLE content_codes (code TEXT PRIMARY KEY, anime_id INTEGER NOT NULL)",
        "INSERT INTO content_codes SELECT code, id FROM animes",
        """CREATE TRIGGER retain_content_code_insert AFTER INSERT ON animes
            BEGIN INSERT INTO content_codes VALUES (NEW.code, NEW.id); END""",
        """CREATE TRIGGER retain_content_code_update AFTER UPDATE OF code ON animes
            WHEN NEW.code <> OLD.code BEGIN
            SELECT RAISE(ABORT, 'Content code already used')
            WHERE EXISTS (SELECT 1 FROM content_codes WHERE code=NEW.code AND anime_id<>NEW.id);
            INSERT OR IGNORE INTO content_codes VALUES (NEW.code, NEW.id);
            END""",
        "CREATE UNIQUE INDEX idx_episode_file ON episodes(season_id, file_unique_id) WHERE file_unique_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_views_anime ON anime_views(anime_id)",
        "CREATE INDEX idx_views_time ON anime_views(viewed_at)",
        "CREATE INDEX idx_views_season ON anime_views(season_id)",
        "CREATE INDEX idx_catalog ON animes(visible, kind, title COLLATE NOCASE)",
    ):
        conn.execute(statement)


def content(anime_id):
    with connection() as conn:
        return _content(conn, anime_id)


def anime_content(anime_id):
    item = content(anime_id)
    return item if item and item["kind"] == "anime" else None


def _content(conn, anime_id):
    return conn.execute("""
        SELECT a.*,
            (SELECT COUNT(*) FROM seasons WHERE anime_id=a.id) AS season_count,
            (SELECT COUNT(*) FROM episodes e JOIN seasons s ON s.id=e.season_id
             WHERE s.anime_id=a.id AND e.video_file_id IS NOT NULL) AS episode_count,
            (SELECT COUNT(*) FROM standalone_videos WHERE anime_id=a.id AND kind='film') AS film_count,
            (SELECT COUNT(*) FROM standalone_videos WHERE anime_id=a.id AND kind='ova') AS ova_count,
            (SELECT COUNT(*) FROM anime_views WHERE anime_id=a.id) AS views
        FROM animes a WHERE a.id=?
    """, (anime_id,)).fetchone()


def by_code(code, kind):
    with connection() as conn:
        return conn.execute("""SELECT id FROM animes
            WHERE code=? AND visible=1 AND kind=?""", (code, kind)).fetchone()


def by_legacy_code(code, kind):
    with connection() as conn:
        return conn.execute("""SELECT a.id FROM content_codes c JOIN animes a ON a.id=c.anime_id
            WHERE c.code=? AND a.visible=1 AND a.kind=?""", (code, kind)).fetchone()


def catalog(kind="anime", order="az", category=None, offset=0, limit=13):
    ordering = {
        "new": "a.created_at DESC NULLS LAST, a.id DESC",
        "popular": "(SELECT COUNT(*) FROM anime_views v WHERE v.anime_id=a.id) DESC, a.title, a.id",
        "year": "a.release_year DESC NULLS LAST, a.title, a.id",
    }
    condition = ""
    params = [kind]
    if order == "year" and category is not None:
        condition = "AND a.release_year=?"
        params.append(category)
    if order == "genre":
        # Janrlar vergul bilan ajratilgan. Python Unicode casefold ishlatadi.
        rows = catalog(kind, limit=-1)
        rows = [row for row in rows if any(
            item.strip().casefold() == category.casefold() for item in (row["genre"] or "").split(",")
        )]
        return rows[offset:None if limit < 0 else offset + limit]
    with connection() as conn:
        sort = f"{title_order(conn)}, a.id" if order == "az" else ordering[order]
        if limit < 0 and not isinstance(conn, sqlite3.Connection):
            limit = None
        return conn.execute(f"""SELECT a.* FROM animes a WHERE a.visible=1 AND a.kind=?
            {condition} ORDER BY {sort} LIMIT ? OFFSET ?""",
            (*params, limit, offset)).fetchall()


def utc_text(moment=None):
    return (moment or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S")


def create_draft(data, poster, seasons=0):
    with connection() as conn:
        cursor = conn.execute("""INSERT INTO animes
            (code,title,genre,release_year,description,poster_file_id,kind,country,visible,created_at)
            VALUES (?,?,?,?,?,?,?,?,0,?) RETURNING id""",
            (data["code"], data["title"], data["genre"], data["release_year"],
             data["description"], poster, data["kind"], data.get("country"), utc_text()))
        anime_id = cursor.fetchone()[0]
        conn.cursor().executemany("INSERT INTO seasons(anime_id,season_number) VALUES (?,?)",
                                  ((anime_id, number) for number in range(1, seasons + 1)))
        return anime_id


def update_media(anime_id, field, file_id, media_type=None):
    with connection() as conn:
        if field == "poster":
            return conn.execute("UPDATE animes SET poster_file_id=? WHERE id=?", (file_id, anime_id)).rowcount
        return conn.execute("""UPDATE animes SET movie_file_id=?,movie_media_type=?
            WHERE id=? AND kind='movie'""", (file_id, media_type, anime_id)).rowcount


def announcement(anime_id):
    with connection() as conn:
        return conn.execute("SELECT * FROM announcements WHERE anime_id=?", (anime_id,)).fetchone()


def claim_announcement(anime_id, previous_post=None):
    with connection() as conn:
        lock_writes(conn, "animes", "announcements")
        item = _content(conn, anime_id)
        if not item or item["kind"] != "anime" or not valid_code(item["code"]):
            return "incomplete", item
        if not (item["episode_count"] or item["film_count"] or item["ova_count"]):
            return "incomplete", item
        row = conn.execute("SELECT status, message_id FROM announcements WHERE anime_id=?", (anime_id,)).fetchone()
        if previous_post is not None:
            if not row or row["status"] not in ("sent", "missing") or (
                row["status"], row["message_id"]
            ) != previous_post:
                return "stale", item
        elif row and row["status"] != "failed":
            return row["status"], item
        conn.execute("""INSERT INTO announcements(anime_id,status) VALUES (?,'sending')
            ON CONFLICT(anime_id) DO UPDATE SET status='sending'""", (anime_id,))
        conn.execute("UPDATE animes SET visible=1 WHERE id=?", (anime_id,))
        return "claimed", item


def mark_announcement_missing(anime_id, message_id):
    with connection() as conn:
        return bool(conn.execute("""UPDATE announcements SET status='missing'
            WHERE anime_id=? AND status='sent' AND message_id=?""", (anime_id, message_id)).rowcount)


def restore_announcement(anime_id, previous_post):
    status, message_id = previous_post
    with connection() as conn:
        conn.execute("""UPDATE announcements SET status=?
            WHERE anime_id=? AND status='sending' AND message_id=?""", (status, anime_id, message_id))


def finish_announcement(anime_id, status, chat_id=None, message_id=None, poster_file_id=None, *, is_text=False):
    with connection() as conn:
        return conn.execute("""UPDATE announcements SET status=?, chat_id=?, message_id=?, poster_file_id=?, is_text=?
            WHERE anime_id=? AND status='sending'""",
            (status, str(chat_id) if chat_id is not None else None, message_id, poster_file_id, int(is_text), anime_id)).rowcount


def remember_announcement_poster(anime_id, message_id, poster_file_id):
    with connection() as conn:
        conn.execute("""UPDATE announcements SET poster_file_id=?
            WHERE anime_id=? AND message_id=? AND status='sent'""", (poster_file_id, anime_id, message_id))


def valid_code(code):
    return bool(code and len(code) <= 58 and code.isascii()
                and all(char.isalnum() or char in "_-" for char in code))


def statistics():
    with connection() as conn:
        periods = {}
        for days in (0, 7, 30):
            periods[days] = conn.execute("""SELECT COUNT(*) AS total, COUNT(DISTINCT user_id) AS users
                FROM anime_views WHERE episode_id<>0 AND (?=0 OR viewed_at >= ?)""",
                (days, utc_text(datetime.now(UTC) - timedelta(days=days)))).fetchone()
        popular = conn.execute("""SELECT a.title, COUNT(*) AS total FROM anime_views v
            JOIN animes a ON a.id=v.anime_id WHERE a.kind='anime' AND a.visible=1
            GROUP BY a.id ORDER BY total DESC, a.id LIMIT 1""").fetchone()
        favorite = conn.execute("""SELECT a.title, COUNT(*) AS total FROM favorites f
            JOIN animes a ON a.id=f.anime_id WHERE a.visible=1 AND a.kind='anime'
            GROUP BY a.id ORDER BY total DESC, a.id LIMIT 1""").fetchone()
        season = conn.execute("""SELECT a.title || ' · ' || s.season_number || '-fasl' AS title,
            COUNT(*) AS total FROM anime_views v JOIN seasons s ON s.id=v.season_id
            JOIN animes a ON a.id=s.anime_id WHERE a.visible=1
            GROUP BY s.id, a.title ORDER BY total DESC, s.id LIMIT 1""").fetchone()
        return periods, popular, favorite, season


def announcement_entries(anime_id, offset, limit):
    with connection() as conn:
        return conn.execute("""SELECT id, number, kind, title FROM (
            SELECT s.id, s.season_number AS number, 0 AS sort_order, 'season' AS kind, '' AS title
            FROM seasons s WHERE s.anime_id=? AND EXISTS (
                SELECT 1 FROM episodes e WHERE e.season_id=s.id AND e.video_file_id <> ''
            )
            UNION ALL
            SELECT id, number, CASE WHEN kind='film' THEN 1 ELSE 2 END, kind, title
            FROM standalone_videos WHERE anime_id=? AND file_id <> ''
        ) entries ORDER BY sort_order, number, id LIMIT ? OFFSET ?""",
                            (anime_id, anime_id, limit, offset)).fetchall()


def standalone_videos(anime_id, offset=0, limit=13):
    with connection() as conn:
        return conn.execute("""SELECT * FROM standalone_videos WHERE anime_id=?
            ORDER BY kind, number LIMIT ? OFFSET ?""", (anime_id, limit, offset)).fetchall()


def standalone_video(video_id):
    with connection() as conn:
        return conn.execute("SELECT * FROM standalone_videos WHERE id=?", (video_id,)).fetchone()


def save_video(anime_id, kind, number, title, description, file_id, media_type, video_id=None, release_year=None, country=None, genre=None):
    with connection() as conn:
        lock_writes(conn, "animes", "standalone_videos")
        if not conn.execute("SELECT 1 FROM animes WHERE id=? AND kind='anime'", (anime_id,)).fetchone():
            return None
        values = (number, title, description, file_id, media_type, release_year, country, genre)
        if video_id is None:
            return conn.execute("""INSERT INTO standalone_videos
                (number,title,description,file_id,media_type,release_year,country,genre,anime_id,kind)
                VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id""", (*values, anime_id, kind)).fetchone()[0]
        changed = conn.execute("""UPDATE standalone_videos SET number=?,title=?,description=?,file_id=?,media_type=?,
            release_year=?,country=?,genre=?
            WHERE id=? AND anime_id=? AND kind=?""", (*values, video_id, anime_id, kind)).rowcount
        return video_id if changed else None


def delete_video(video_id):
    with connection() as conn:
        return conn.execute("DELETE FROM standalone_videos WHERE id=?", (video_id,)).rowcount


def save_caption(anime_id, mode, text, link):
    with connection() as conn:
        return conn.execute("""UPDATE animes SET caption_mode=?,caption_text=?,caption_link=?
            WHERE id=?""", (mode, text, link, anime_id)).rowcount


def news(news_id=None, offset=0):
    with connection() as conn:
        query = "SELECT n.*,a.title AS anime_title, a.code AS anime_code, a.visible AS anime_visible FROM anime_news n LEFT JOIN animes a ON a.id=n.anime_id"
        if news_id is not None:
            return conn.execute(query + " WHERE n.id=?", (news_id,)).fetchone()
        return conn.execute(query + " ORDER BY n.id DESC LIMIT 11 OFFSET ?", (offset,)).fetchall()


def save_news(anime_id, kind, title, body, photo, news_id=None):
    with connection() as conn:
        if news_id is None:
            return conn.execute("""INSERT INTO anime_news(anime_id,kind,title,body,photo)
                VALUES(?,?,?,?,?) RETURNING id""", (anime_id, kind, title, body, photo)).fetchone()[0]
        return conn.execute("""UPDATE anime_news SET anime_id=?,kind=?,title=?,body=?,photo=?
            WHERE id=?""", (anime_id, kind, title, body, photo, news_id)).rowcount


def news_action(news_id, action):
    statements = {
        "delete": "DELETE FROM anime_news WHERE id=?",
        "claim": "UPDATE anime_news SET published_at='pending' WHERE id=? AND published_at IS NULL",
        "sent": "UPDATE anime_news SET published_at=? WHERE id=? AND published_at='pending'",
        "release": "UPDATE anime_news SET published_at=NULL WHERE id=? AND published_at='pending'",
    }
    with connection() as conn:
        return conn.execute(statements[action], (utc_text(), news_id) if action == "sent" else (news_id,)).rowcount


def add_comment(anime_id, user_id, name, username, body):
    with connection() as conn:
        lock_writes(conn, "animes", "anime_comments")
        item = conn.execute("SELECT title,code FROM animes WHERE id=? AND visible=1 AND kind='anime'",
                            (anime_id,)).fetchone()
        if not item:
            return "missing"
        if conn.execute("""SELECT 1 FROM anime_comments
            WHERE user_id=? AND created_at > ?""", (user_id, utc_text(datetime.now(UTC) - timedelta(minutes=1)))).fetchone():
            return "limited"
        conn.execute("""INSERT INTO anime_comments(anime_id,anime_title,anime_code,user_id,name,username,body)
            VALUES(?,?,?,?,?,?,?)""", (anime_id, item["title"], item["code"], user_id, name, username, body))
        return "saved"


def comments(comment_id=None, offset=0):
    with connection() as conn:
        if comment_id is not None:
            return conn.execute("SELECT * FROM anime_comments WHERE id=?", (comment_id,)).fetchone()
        return conn.execute("SELECT * FROM anime_comments ORDER BY id DESC LIMIT 11 OFFSET ?", (offset,)).fetchall()


def delete_comment(comment_id):
    with connection() as conn:
        return conn.execute("DELETE FROM anime_comments WHERE id=?", (comment_id,)).rowcount


def metric(kind, subject=0, *, count=1):
    with connection() as conn:
        conn.execute("""INSERT INTO bot_metrics VALUES(?,?,?,?)
            ON CONFLICT(day,kind,subject) DO UPDATE SET total=bot_metrics.total+excluded.total""", (datetime.now(UTC).date().isoformat(), kind, subject, count))


def active_user(user_id):
    with connection() as conn:
        today = datetime.now(UTC).date().isoformat()
        conn.execute("""INSERT INTO bot_users VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET last_active=excluded.last_active
            WHERE bot_users.last_active<>excluded.last_active""", (user_id, today))


def prune_statistics():
    days = os.getenv("STATISTICS_RETENTION_DAYS", "90")
    days = int(days) if days.isascii() and days.isdecimal() and len(days) <= 4 and int(days) else 90
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with connection() as conn:
        conn.execute("DELETE FROM bot_metrics WHERE day < ?", (cutoff.date().isoformat(),))
        conn.execute("DELETE FROM bot_users WHERE last_active < ?", (cutoff.date().isoformat(),))
        if os.getenv("STATISTICS_RETENTION_DAYS"):
            conn.execute("DELETE FROM anime_views WHERE viewed_at < ?", (utc_text(cutoff),))


def owner_statistics():
    prune_statistics()
    with connection() as conn:
        users = conn.execute("SELECT COUNT(*), COUNT(CASE WHEN last_active=? THEN 1 END) FROM bot_users",
                             (datetime.now(UTC).date().isoformat(),)).fetchone()
        metrics = dict(conn.execute("SELECT kind,SUM(total) FROM bot_metrics GROUP BY kind"))
        opened = conn.execute("""SELECT a.title,SUM(m.total) AS total FROM bot_metrics m
            JOIN animes a ON a.id=m.subject WHERE m.kind='open'
            GROUP BY a.id ORDER BY total DESC,a.id LIMIT 5""").fetchall()
        episodes = conn.execute("""SELECT a.title,s.season_number,e.episode_number,COUNT(*) AS total
            FROM anime_views v JOIN episodes e ON e.id=v.episode_id JOIN seasons s ON s.id=e.season_id
            JOIN animes a ON a.id=s.anime_id GROUP BY e.id, a.title, s.season_number ORDER BY total DESC,e.id LIMIT 5""").fetchall()
        return users, metrics, opened, episodes
