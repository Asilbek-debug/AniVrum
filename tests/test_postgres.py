import asyncio
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from database import catalog, db, import_postgres, postgres


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "fixture.db"
        self.enterContext(patch.object(db, "DB_PATH", self.path))
        self.enterContext(patch.dict(os.environ, {
            "DATABASE_URL": "", "ANIVRUM_REQUIRE_POSTGRES": "", "STATISTICS_RETENTION_DAYS": "",
        }))

    def v3_fixture(self):
        with db.connection() as conn:
            catalog._migrate_v1(conn)
            conn.execute("ALTER TABLE animes ADD COLUMN country TEXT")
            conn.execute("ALTER TABLE announcements ADD COLUMN poster_file_id TEXT")
            conn.execute("DROP TRIGGER retain_content_code_insert")
            conn.execute("DROP TRIGGER retain_content_code_update")
            conn.execute("PRAGMA user_version = 3")
            conn.execute("INSERT INTO animes(id,code,title,poster_file_id) VALUES (9,'009','Anime Ω','poster-file')")
            conn.execute("INSERT INTO seasons(id,anime_id,season_number) VALUES (31,9,1)")
            conn.execute("""INSERT INTO episodes(id,season_id,episode_number,video_file_id,file_unique_id)
                VALUES (81,31,1,'video-file','unique-file')""")
            conn.execute("INSERT INTO content_codes VALUES ('old-009',9),('deleted-010',10)")
            conn.execute("INSERT INTO favorites(user_id,anime_id) VALUES (9000000001,9)")
            conn.execute("""INSERT INTO anime_views(anime_id,user_id,episode_id,viewed_at,season_id)
                VALUES (9,9000000001,81,'2021-03-04 05:06:07',31),(10,9000000001,999,NULL,NULL)""")
            conn.execute("INSERT INTO announcements(anime_id,status,chat_id,message_id) VALUES (9,'sent','-100123',654)")
            conn.execute("UPDATE sqlite_sequence SET seq=1000 WHERE name='animes'")

    def test_v3_wal_snapshot_preserves_source_and_reads_committed_rows(self):
        self.v3_fixture()
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("UPDATE episodes SET video_file_id='committed' WHERE id=81")
            writer.commit()
            writer.execute("UPDATE episodes SET video_file_id='uncommitted' WHERE id=81")
            with import_postgres.snapshot(self.path) as (source, version):
                self.assertEqual(version, 3)
                self.assertEqual(source.execute("PRAGMA user_version").fetchone()[0], 4)
                self.assertEqual(source.execute("SELECT video_file_id FROM episodes").fetchone()[0], "committed")
                self.assertEqual(import_postgres.counts(source)["anime_views"], 2)
            self.assertEqual(writer.execute("PRAGMA user_version").fetchone()[0], 3)
            writer.rollback()

    def test_required_postgres_prevents_sqlite_fallback(self):
        with patch.dict(os.environ, {"ANIVRUM_REQUIRE_POSTGRES": "true"}), self.assertRaises(RuntimeError):
            with db.connection():
                self.fail("unexpected SQLite fallback")
        self.assertFalse(self.path.exists())


class PostgresTests(unittest.TestCase):
    def setUp(self):
        bootstrap = os.getenv("ANIVRUM_TEST_POSTGRES_URL")
        if not bootstrap or postgres.psycopg is None:
            self.skipTest("ANIVRUM_TEST_POSTGRES_URL with a disposable loopback cluster is required")
        psycopg = postgres.psycopg
        options = psycopg.conninfo.conninfo_to_dict(bootstrap)
        if options.get("host") != "127.0.0.1" or options.get("hostaddr") not in (None, "127.0.0.1"):
            self.fail("PostgreSQL tests require a cluster on 127.0.0.1")
        # Supply fixed host options so inherited libpq service configuration cannot redirect tests.
        options.pop("service", None)
        options["hostaddr"] = "127.0.0.1"
        self.bootstrap = psycopg.conninfo.make_conninfo(**options)
        self.name = f"anivrum_test_{uuid4().hex}"
        with psycopg.connect(self.bootstrap, autocommit=True) as connection:
            connection.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(self.name)))
        self.addCleanup(self.drop_database)
        self.url = psycopg.conninfo.make_conninfo(self.bootstrap, dbname=self.name)

        fixture = SnapshotTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.path = fixture.path
        fixture.v3_fixture()

    def drop_database(self):
        psycopg = postgres.psycopg
        with psycopg.connect(self.bootstrap, autocommit=True) as connection:
            connection.execute(psycopg.sql.SQL("DROP DATABASE {}").format(psycopg.sql.Identifier(self.name)))

    def import_fixture(self):
        with import_postgres.snapshot(self.path) as (source, version):
            with postgres.connection(self.url) as target:
                return import_postgres.transfer(source, target), version

    def test_import_v3_value_verification_identity_and_reimport_safety(self):
        counts, version = self.import_fixture()
        self.assertEqual(version, 3)
        self.assertEqual((counts["animes"], counts["episodes"], counts["anime_views"], counts["content_codes"]),
                         (1, 1, 2, 2))
        with self.assertRaisesRegex(import_postgres.ImportCheckError, "bo‘sh emas"):
            self.import_fixture()
        with import_postgres.snapshot(self.path) as (source, _), postgres.connection(self.url) as target:
            target.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            self.assertEqual(import_postgres.verify(source, target), counts)
        with patch.dict(os.environ, {"DATABASE_URL": self.url}):
            self.assertEqual(catalog.by_legacy_code("old-009", "anime")[0], 9)
            self.assertEqual(db.get_episode_by_id(81)["video_file_id"], "video-file")
            self.assertEqual(db.get_user_favorites(9000000001)[0]["id"], 9)
            self.assertEqual(catalog.create_draft(draft(), None), 1001)

    def test_import_v4_preserves_movies_comments_news_and_detects_changed_value(self):
        catalog.migrate()
        catalog.save_video(9, "film", 1, "Film", None, "film-id", "video")
        catalog.save_video(9, "ova", 1, "OVA", "Description", "ova-id", "document")
        news_id = catalog.save_news(9, "film", "News", "Body", "photo")
        catalog.news_action(news_id, "claim")
        catalog.save_caption(9, "custom", "Custom", "channel")
        catalog.add_comment(9, 9000000001, "Tester", "local", "Comment")
        catalog.active_user(9000000001)
        catalog.metric("search")
        counts, version = self.import_fixture()
        self.assertEqual((counts["standalone_videos"], counts["anime_news"], counts["anime_comments"], version),
                         (2, 1, 1, 4))
        with postgres.connection(self.url) as target:
            target.execute("UPDATE episodes SET video_file_id=? WHERE id=?", ("different", 81))
        with import_postgres.snapshot(self.path) as (source, _), postgres.connection(self.url) as target:
            with self.assertRaisesRegex(import_postgres.ImportCheckError, "episodes"):
                import_postgres.verify(source, target)

    def test_failed_import_rolls_back_all_rows_and_schema(self):
        with db.connection() as source:
            source.execute("UPDATE episodes SET video_file_id=? WHERE id=81", ("cannot\x00store",))
        with self.assertRaises(db.DATABASE_ERRORS):
            self.import_fixture()
        with postgres.connection(self.url) as target:
            self.assertIsNone(target.execute("SELECT to_regclass('anivrum.animes')").fetchone()[0])

    def test_runtime_queries_and_concurrent_writers_on_postgres(self):
        with patch.dict(os.environ, {"DATABASE_URL": self.url}):
            catalog.migrate()
            catalog.migrate()
            anime = catalog.create_draft(draft(), "poster", 1)
            season = db.get_anime_seasons(anime)[0]["id"]
            with ThreadPoolExecutor(max_workers=3) as workers:
                numbers = list(workers.map(lambda n: db.add_episode_auto(season, f"id-{n}"), range(6)))
                claims = list(workers.map(lambda _: catalog.claim_announcement(anime)[0], range(3)))
            self.assertEqual(sorted(numbers), list(range(1, 7)))
            self.assertEqual(claims.count("claimed"), 1)
            episode = db.get_season_episodes(season)[0]["id"]
            catalog.finish_announcement(anime, "sent", -100123, 17, "poster", is_text=False)
            self.assertEqual(catalog.announcement(anime)["chat_id"], "-100123")
            self.assertEqual([row["id"] for row in catalog.catalog(limit=-1)], [anime])
            self.assertEqual(catalog.catalog(order="genre", category="Drama")[0]["id"], anime)
            film = catalog.save_video(anime, "film", 1, "Standalone", None, "film", "video")
            self.assertEqual(db.search_animes("Standalone")[0]["id"], anime)
            self.assertEqual(catalog.save_video(anime, "film", 2, "Edited", None, "film2", "video", film), film)
            self.assertEqual(catalog.standalone_video(film)["file_id"], "film2")
            news = catalog.save_news(anime, "film", "News", "Body", None)
            self.assertEqual(catalog.news_action(news, "claim"), 1)
            self.assertEqual(catalog.news_action(news, "sent"), 1)
            self.assertNotEqual(catalog.news(news)["published_at"], "pending")
            self.assertTrue(db.add_favorite(9000000001, anime))
            self.assertFalse(db.add_favorite(9000000001, anime))
            db.add_anime_view(anime, 9000000001, episode, season)
            self.assertEqual(db.get_top_animes()[0]["views"], 1)
            self.assertEqual(tuple(catalog.statistics()[0][7]), (1, 1))
            self.assertEqual(catalog.add_comment(anime, 9000000001, "Name", None, "Comment"), "saved")
            self.assertEqual(catalog.add_comment(anime, 9000000001, "Name", None, "Again"), "limited")
            catalog.active_user(9000000001)
            catalog.active_user(9000000001)
            catalog.metric("film", film)
            catalog.metric("film", film)
            users, totals, _, episodes = catalog.owner_statistics()
            self.assertEqual((tuple(users), totals["film"], episodes[0]["total"]), ((1, 1), 2, 1))
            self.assertTrue(db.delete_anime(anime))
            self.assertIsNone(catalog.standalone_video(film))
            self.assertIsNone(catalog.news(news)["anime_id"])
            self.assertIsNone(catalog.comments()[0]["anime_id"])

    def test_repeated_bot_startup_keeps_imported_postgres_data(self):
        from bot import main

        self.import_fixture()
        with patch.dict(os.environ, {
            "DATABASE_URL": self.url, "BOT_TOKEN": "123456:offline", "ADMIN_ID": "100",
        }), patch.object(main.dp, "start_polling", new_callable=AsyncMock) as polling:
            asyncio.run(main.main(load_local_env=False))
            asyncio.run(main.main(load_local_env=False))
            self.assertEqual(polling.await_count, 2)
            self.assertEqual(catalog.by_legacy_code("old-009", "anime")[0], 9)
            self.assertEqual(db.get_episode_by_id(81)["video_file_id"], "video-file")
        with closing(sqlite3.connect(self.path)) as source:
            self.assertEqual(source.execute("PRAGMA user_version").fetchone()[0], 3)


def draft():
    return dict(code="1001", title="Anime", genre="Drama", release_year=2026, description=None, kind="anime")
