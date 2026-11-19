
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

# Ma'lumotlar bazasi joylashuvi
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "anivrum.db"
DB_PATH = DEFAULT_DB_PATH


@contextmanager
def connection():
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.row_factory = sqlite3.Row
        yield conn


def create_database():
    with connection() as conn:
        cursor = conn.cursor()

        # Animelar jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS animes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                genre TEXT,
                description TEXT,
                release_year INTEGER
            )
        """)

        conn.commit()


if __name__ == "__main__":
    create_database()


# Bazaga yangi anime qo'shish
def add_anime(code, title, genre, description, release_year):
    with connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO animes
            (code, title, genre, description, release_year)
            VALUES (?, ?, ?, ?, ?)
        """, (code, title, genre, description, release_year))

        conn.commit()


# Birinchi sinov animesini qo'shish
if __name__ == "__main__":
    add_anime(
        code="1001",
        title="Sinov Anime",
        genre="Fantastika, Sarguzasht",
        description="AniVrum uchun birinchi sinov animesi.",
        release_year=2026
    )


# Bazadagi barcha animelarni olish
def get_all_animes():
    with connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM animes
            WHERE kind = 'anime'
            ORDER BY title ASC
        """)

        return cursor.fetchall()


# Animeni ID orqali topish
def get_anime_by_id(anime_id):
    with connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM animes WHERE id = ? AND kind = 'anime'",
            (anime_id,)
        )

        return cursor.fetchone()


# Anime fasllari va qismlari uchun jadvallar
def create_seasons_episodes_tables():
    with connection() as conn:
        cursor = conn.cursor()

        # Fasllar jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                anime_id INTEGER NOT NULL,
                season_number INTEGER NOT NULL,
                FOREIGN KEY (anime_id) REFERENCES animes(id),
                UNIQUE (anime_id, season_number)
            )
        """)

        # Qismlar jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_id INTEGER NOT NULL,
                episode_number INTEGER NOT NULL,
                title TEXT,
                video_file_id TEXT,
                FOREIGN KEY (season_id) REFERENCES seasons(id),
                UNIQUE (season_id, episode_number)
            )
        """)

        conn.commit()


# Animega yangi fasl qo'shish
def add_season(anime_id, season_number):
    with connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO seasons
            (anime_id, season_number)
            VALUES (?, ?)
        """, (anime_id, season_number))

        conn.commit()


# Animening barcha fasllarini olish
def get_anime_seasons(anime_id):
    with connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM seasons
            WHERE anime_id = ?
            ORDER BY season_number ASC
        """, (anime_id,))

        return cursor.fetchall()


# Faslga yangi qism qo'shish
def add_episode(season_id, episode_number, title, video_file_id=None):
    with connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO episodes
            (season_id, episode_number, title, video_file_id)
            VALUES (?, ?, ?, ?)
        """, (season_id, episode_number, title, video_file_id))

        conn.commit()


# Fasldagi barcha qismlarni olish
def get_season_episodes(season_id):
    with connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM episodes
            WHERE season_id = ?
            ORDER BY episode_number ASC
        """, (season_id,))

        return cursor.fetchall()


# ID orqali bitta qismni olish
def get_episode_by_id(episode_id):
    with connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                episodes.*,
                seasons.season_number,
                animes.title AS anime_title
            FROM episodes
            JOIN seasons ON episodes.season_id = seasons.id
            JOIN animes ON seasons.anime_id = animes.id
            WHERE episodes.id = ?
        """, (episode_id,))

        return cursor.fetchone()


# Animega tegishli faslni olish
def get_season_by_id(season_id):
    with connection() as conn:

        return conn.execute("""
            SELECT seasons.*, animes.title AS anime_title
            FROM seasons
            JOIN animes ON animes.id = seasons.anime_id
            WHERE seasons.id = ?
        """, (season_id,)).fetchone()


# Fasl raqami orqali faslni topish
def get_season_by_number(anime_id, season_number):
    with connection() as conn:

        return conn.execute("""
            SELECT * FROM seasons
            WHERE anime_id = ? AND season_number = ?
        """, (anime_id, season_number)).fetchone()


# Faslga yangi qismni avtomatik raqamlab qo'shish
def add_episode_auto(season_id, video_file_id, media_type='video', file_unique_id=None):
    with connection() as conn:
        cursor = conn.cursor()

        cursor.execute("BEGIN IMMEDIATE")
        if cursor.execute(
            "SELECT 1 FROM episodes WHERE season_id=? AND video_file_id=?",
            (season_id, video_file_id),
        ).fetchone():
            raise sqlite3.IntegrityError("Qism videosi takrorlangan.")

        cursor.execute("""
            SELECT COALESCE(MAX(episode_number), 0) + 1
            FROM episodes
            WHERE season_id = ?
        """, (season_id,))

        next_number = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO episodes
            (season_id, episode_number, title, video_file_id, media_type, file_unique_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            season_id,
            next_number,
            f"{next_number}-qism",
            video_file_id, media_type, file_unique_id
        ))

        conn.commit()
        return next_number


# ==========================================
# ANIVRUM - ADMIN PANEL 2.0 DATABASE
# ==========================================


# Anime ma'lumotlarini tahrirlash
def update_anime(anime_id, code, title, genre, description, release_year):
    with connection() as conn:
        cursor = conn.execute("""
            UPDATE animes
            SET code = ?,
                title = ?,
                genre = ?,
                description = ?,
                release_year = ?
            WHERE id = ?
        """, (
            code, title, genre, description,
            release_year, anime_id
        ))

        return cursor.rowcount > 0


# Anime nomini o'zgartirish
def update_anime_title(anime_id, title):
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE animes SET title = ? WHERE id = ?",
            (title, anime_id)
        )
        return cursor.rowcount > 0


# Anime janrini o'zgartirish
def update_anime_genre(anime_id, genre):
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE animes SET genre = ? WHERE id = ?",
            (genre, anime_id)
        )
        return cursor.rowcount > 0


def update_anime_country(anime_id, country):
    with connection() as conn:
        cursor = conn.execute("UPDATE animes SET country = ? WHERE id = ?", (country, anime_id))
        return cursor.rowcount > 0


# Anime tavsifini o'zgartirish
def update_anime_description(anime_id, description):
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE animes SET description = ? WHERE id = ?",
            (description, anime_id)
        )
        return cursor.rowcount > 0


# Anime kodini o'zgartirish
def update_anime_code(anime_id, code):
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE animes SET code = ? WHERE id = ?",
            (code, anime_id)
        )
        return cursor.rowcount > 0


# Anime yilini o'zgartirish
def update_anime_year(anime_id, year):
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE animes SET release_year = ? WHERE id = ?",
            (year, anime_id)
        )
        return cursor.rowcount > 0


# Anime va unga tegishli barcha fasl/qismlarni o'chirish
def delete_anime(anime_id):
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute("""
            DELETE FROM episodes
            WHERE season_id IN (
                SELECT id FROM seasons WHERE anime_id = ?
            )
        """, (anime_id,))

        cursor.execute(
            "DELETE FROM seasons WHERE anime_id = ?",
            (anime_id,)
        )

        cursor.execute(
            "DELETE FROM animes WHERE id = ?",
            (anime_id,)
        )

        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted


# Fasl raqamini o'zgartirish
def update_season_number(season_id, new_number):
    with connection() as conn:
        cursor = conn.execute("""
            UPDATE seasons
            SET season_number = ?
            WHERE id = ?
        """, (new_number, season_id))

        return cursor.rowcount > 0


# Fasl va uning barcha qismlarini o'chirish
def delete_season(season_id):
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            "DELETE FROM episodes WHERE season_id = ?",
            (season_id,)
        )

        cursor.execute(
            "DELETE FROM seasons WHERE id = ?",
            (season_id,)
        )

        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted


# Qism raqamini o'zgartirish
def update_episode_number(episode_id, new_number):
    with connection() as conn:
        cursor = conn.execute("""
            UPDATE episodes
            SET episode_number = ?,
                title = ?
            WHERE id = ?
        """, (
            new_number,
            f"{new_number}-qism",
            episode_id
        ))

        return cursor.rowcount > 0


# Qism videosini almashtirish
def update_episode_video(episode_id, video_file_id, media_type="video", file_unique_id=None):
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("""
            SELECT 1 FROM episodes WHERE season_id=(SELECT season_id FROM episodes WHERE id=?)
            AND id<>? AND video_file_id=?
        """, (episode_id, episode_id, video_file_id)).fetchone():
            raise sqlite3.IntegrityError("Qism videosi takrorlangan.")
        cursor = conn.execute("""
            UPDATE episodes SET video_file_id=?, media_type=?, file_unique_id=? WHERE id=?
        """, (video_file_id, media_type, file_unique_id, episode_id))
        return cursor.rowcount > 0


# Bitta qismni o'chirish
def delete_episode(episode_id):
    with connection() as conn:
        cursor = conn.execute(
            "DELETE FROM episodes WHERE id = ?",
            (episode_id,)
        )

        return cursor.rowcount > 0


# ==========================================
# ANIVRUM - AQLLI ANIME QIDIRUV TIZIMI
# ==========================================

from difflib import SequenceMatcher
import re


def normalize_text(text):
    """Matnni qidiruv uchun bir xil shaklga keltiradi."""
    text = str(text).casefold().strip()
    text = text.replace("ʻ", "'").replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    return text


def search_animes(query):
    query = normalize_text(query)

    if not query:
        return []

    with connection() as conn:

        rows = conn.execute("""
            SELECT id, code, title, genre,
                   description, release_year
            FROM animes WHERE visible=1 AND kind='anime'
        """).fetchall()

    results = []

    for row in rows:
        anime = dict(row)

        title = normalize_text(anime["title"])
        code = normalize_text(anime["code"])

        # Kod to'liq mos kelsa
        if query == code:
            score = 1.0

        # Nom to'liq mos kelsa
        elif query == title:
            score = 1.0

        # Nomning bir qismi mos kelsa
        elif query in title:
            score = 0.95

        elif query.isascii() and len(query) == 4 and query.isdigit() and query == str(anime["release_year"]):
            score = 0.90
        elif query in normalize_text(anime["genre"] or ""):
            score = 0.85
        else:
            # Xato yozilgan harflarni solishtirish
            full_similarity = SequenceMatcher(
                None, query, title
            ).ratio()

            # Alohida so'zlarni ham tekshirish
            words = title.split()

            word_similarity = max(
                (
                    SequenceMatcher(
                        None, query, word
                    ).ratio()
                    for word in words
                ),
                default=0
            )

            score = max(
                full_similarity,
                word_similarity
            )

        # Kamida 60% o'xshashlik
        if score >= 0.60:
            results.append((score, anime))

    # Eng o'xshash anime birinchi chiqadi
    results.sort(
        key=lambda item: (
            -item[0],
            item[1]["title"].casefold()
        )
    )

    # Eng yaxshi 20 ta natija
    return [
        anime
        for score, anime in results[:20]
    ]


# ==========================================
# ANIVRUM - SEVIMLILAR BAZASI
# ==========================================

def create_favorites_table():
    with connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                anime_id INTEGER NOT NULL,
                UNIQUE(user_id, anime_id)
            )
        """)


def add_favorite(user_id, anime_id):
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO favorites
            (user_id, anime_id)
            SELECT ?, id FROM animes WHERE id = ? AND visible=1 AND kind='anime'
            """,
            (user_id, anime_id)
        )
        return cursor.rowcount > 0


def remove_favorite(user_id, anime_id):
    with connection() as conn:
        cursor = conn.execute(
            """
            DELETE FROM favorites
            WHERE user_id = ? AND anime_id = ?
            """,
            (user_id, anime_id)
        )
        return cursor.rowcount > 0


def is_favorite(user_id, anime_id):
    with connection() as conn:
        result = conn.execute(
            """
            SELECT 1 FROM favorites
            WHERE user_id = ? AND anime_id = ?
            """,
            (user_id, anime_id)
        ).fetchone()
        return result is not None


def get_user_favorites(user_id):
    with connection() as conn:

        rows = conn.execute(
            """
            SELECT a.*
            FROM favorites AS f
            JOIN animes AS a ON a.id = f.anime_id
            WHERE f.user_id = ? AND a.visible=1 AND a.kind='anime'
            ORDER BY a.title COLLATE NOCASE
            """,
            (user_id,)
        ).fetchall()

        return [dict(row) for row in rows]


# ==========================================
# ANIVRUM - TOP ANIMELAR STATISTIKASI
# ==========================================

def create_views_table():
    with connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS anime_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                anime_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                episode_id INTEGER NOT NULL,
                viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_views_anime
            ON anime_views(anime_id)
        """)


def add_anime_view(anime_id, user_id, episode_id, season_id=None):
    with connection() as conn:
        conn.execute("""
            INSERT INTO anime_views
            (anime_id, user_id, episode_id, season_id)
            VALUES (?, ?, ?, ?)
        """, (anime_id, user_id, episode_id, season_id))


def get_top_animes(limit=10):
    with connection() as conn:

        rows = conn.execute("""
            SELECT
                a.id,
                a.title,
                a.code,
                COUNT(v.id) AS views
            FROM animes AS a
            JOIN anime_views AS v
                ON a.id = v.anime_id
            WHERE a.visible=1 AND a.kind='anime'
            GROUP BY a.id
            ORDER BY views DESC, a.title ASC
            LIMIT ?
        """, (limit,)).fetchall()

        return [dict(row) for row in rows]
