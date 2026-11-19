"""AniVrum platformasi uchun SQLite migratsiyasi va katalog so'rovlari."""

from database.db import connection


def migrate():
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3):
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
            conn.execute("PRAGMA user_version = 3")


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
        "az": "a.title COLLATE NOCASE, a.id",
        "new": "a.created_at DESC, a.id DESC",
        "popular": "(SELECT COUNT(*) FROM anime_views v WHERE v.anime_id=a.id) DESC, a.title, a.id",
        "year": "a.release_year DESC, a.title, a.id",
        "genre": "a.title COLLATE NOCASE, a.id",
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
        return conn.execute(f"""SELECT a.* FROM animes a WHERE a.visible=1 AND a.kind=?
            {condition} ORDER BY {ordering[order]} LIMIT ? OFFSET ?""",
            (*params, limit, offset)).fetchall()


def create_draft(data, poster, seasons=0):
    with connection() as conn:
        cursor = conn.execute("""INSERT INTO animes
            (code,title,genre,release_year,description,poster_file_id,kind,country,visible,created_at)
            VALUES (?,?,?,?,?,?,?,?,0,CURRENT_TIMESTAMP)""",
            (data["code"], data["title"], data["genre"], data["release_year"],
             data["description"], poster, data["kind"], data.get("country")))
        anime_id = cursor.lastrowid
        conn.executemany("INSERT INTO seasons(anime_id,season_number) VALUES (?,?)",
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
        conn.execute("BEGIN IMMEDIATE")
        item = _content(conn, anime_id)
        if not item or item["kind"] != "anime" or not valid_code(item["code"]) or not item["poster_file_id"]:
            return "incomplete", item
        if not item["episode_count"]:
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


def finish_announcement(anime_id, status, chat_id=None, message_id=None, poster_file_id=None):
    with connection() as conn:
        return conn.execute("""UPDATE announcements SET status=?, chat_id=?, message_id=?, poster_file_id=?
            WHERE anime_id=? AND status='sending'""",
            (status, chat_id, message_id, poster_file_id, anime_id)).rowcount


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
                FROM anime_views WHERE episode_id<>0 AND (?=0 OR viewed_at >= datetime('now', ?))""",
                (days, f"-{days} days")).fetchone()
        popular = conn.execute("""SELECT a.title, COUNT(*) AS total FROM anime_views v
            JOIN animes a ON a.id=v.anime_id WHERE a.kind='anime' AND a.visible=1
            GROUP BY a.id ORDER BY total DESC, a.id LIMIT 1""").fetchone()
        favorite = conn.execute("""SELECT a.title, COUNT(*) AS total FROM favorites f
            JOIN animes a ON a.id=f.anime_id WHERE a.visible=1 AND a.kind='anime'
            GROUP BY a.id ORDER BY total DESC, a.id LIMIT 1""").fetchone()
        season = conn.execute("""SELECT a.title || ' · ' || s.season_number || '-fasl' AS title,
            COUNT(*) AS total FROM anime_views v JOIN seasons s ON s.id=v.season_id
            JOIN animes a ON a.id=s.anime_id WHERE a.visible=1
            GROUP BY s.id ORDER BY total DESC, s.id LIMIT 1""").fetchone()
        return periods, popular, favorite, season
