from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from app import create_app
from config import Config
from db import execute
from utils import save_upload


class Cursor:
    def __init__(self, connection, dictionary):
        self.cursor = connection.raw.cursor()
        self.connection = connection
        self.dictionary = dictionary

    def execute(self, sql, params=()):
        if self.connection.fail_sql and self.connection.fail_sql in sql:
            raise RuntimeError("Injected statement failure")
        self.cursor.execute(sql.replace("%s", "?").replace(" FOR UPDATE", ""), params)

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row is not None and self.dictionary else row

    def fetchall(self):
        return [dict(row) if self.dictionary else row for row in self.cursor.fetchall()]

    def close(self):
        self.cursor.close()


class Connection:
    """SQLite-backed test adapter; no connection to the user's MySQL database."""
    def __init__(self):
        self.raw = sqlite3.connect(":memory:")
        self.raw.row_factory = sqlite3.Row
        self.commits = 0
        self.rollbacks = 0
        self.fail_sql = None
        self.fail_commit = False

    def cursor(self, dictionary=False):
        return Cursor(self, dictionary)

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("Injected commit failure")
        self.raw.commit()
        self.commits += 1

    def rollback(self):
        self.raw.rollback()
        self.rollbacks += 1


class TransactionTests(unittest.TestCase):
    def setUp(self):
        authentication = patch("utils.valid_session", return_value=True)
        authentication.start()
        self.addCleanup(authentication.stop)
        with patch.multiple(Config, SECRET_KEY="s" * 48, DB_PASSWORD="test-only"):
            self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.uploads = Path(self.temp.name) / "uploads"
        self.uploads.mkdir()
        self.app.config["UPLOAD_FOLDER"] = str(self.uploads)
        self.conn = Connection()
        self.addCleanup(self.conn.raw.close)
        self.conn.raw.executescript("""
            CREATE TABLE projects (id INTEGER PRIMARY KEY, owner_id INT, title TEXT,
                description TEXT, language TEXT, is_private INT, status TEXT);
            CREATE TABLE project_languages (project_id INT, language TEXT,
                language_norm TEXT GENERATED ALWAYS AS (lower(language)));
            CREATE TABLE project_activity (project_id INT, user_id INT, action TEXT,
                entity_type TEXT, entity_id INT);
            CREATE TABLE files (id INTEGER PRIMARY KEY, project_id INT, uploaded_by INT,
                filename TEXT, filepath TEXT, filesize INT, sha256 TEXT);
            INSERT INTO projects VALUES (1, 7, 'Original', 'Old description', 'Python', 1, 'active');
            INSERT INTO project_languages(project_id, language) VALUES (1, 'Python');
        """)
        for target, value in (("db.get_conn", self.conn),
                              ("routes.project.current_user", {"id": 7}),
                              ("routes.project.get_project_role", "owner"),
                              ("routes.project.is_project_owner", True)):
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 7

    def seed_file(self):
        folder = self.uploads / "1"
        folder.mkdir(exist_ok=True)
        path = folder / "sample.txt"
        path.write_text("keep me")
        self.conn.raw.execute("INSERT INTO files VALUES (1, 1, 7, 'sample.txt', ?, 7, '')", (str(path),))
        self.conn.raw.commit()
        return path

    def test_edit_failure_restores_metadata_and_language_list(self):
        self.conn.fail_sql = "INSERT INTO project_languages"
        with self.assertRaisesRegex(RuntimeError, "statement failure"):
            self.client.post("/project/1/edit", data={"title": "Changed", "languages": "Rust"})
        self.assertEqual(self.conn.raw.execute("SELECT title FROM projects").fetchone()[0], "Original")
        self.assertEqual(self.conn.raw.execute("SELECT language FROM project_languages").fetchone()[0], "Python")
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_successful_edit_commits_metadata_languages_and_activity_once(self):
        response = self.client.post("/project/1/edit", data={"title": "Changed", "languages": ["Rust", "Go"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.conn.commits, 1)
        self.assertEqual(self.conn.raw.execute("SELECT COUNT(*) FROM project_languages").fetchone()[0], 2)
        self.assertEqual(self.conn.raw.execute("SELECT COUNT(*) FROM project_activity").fetchone()[0], 1)

    def test_activity_failure_rolls_back_new_project(self):
        self.conn.fail_sql = "INSERT INTO project_activity"
        with self.assertRaises(RuntimeError):
            self.client.post("/projects/create", data={"title": "New project", "languages": "Python"})
        self.assertEqual(self.conn.raw.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)
        self.assertEqual(self.conn.raw.execute("SELECT COUNT(*) FROM project_languages").fetchone()[0], 1)

    def test_upload_insert_failure_removes_saved_bytes(self):
        self.conn.fail_sql = "INSERT INTO files"
        with patch("routes.project.fetchone", return_value={"id": 1, "is_private": 1}), \
             patch("routes.project.require_project_role"):
            with self.assertRaises(RuntimeError):
                self.client.post("/project/1", data={"file": (BytesIO(b"hello"), "sample.txt")})
        self.assertEqual(list(self.uploads.rglob("*.txt")), [])
        self.assertEqual(self.conn.raw.execute("SELECT COUNT(*) FROM files").fetchone()[0], 0)

    def test_partial_write_and_empty_upload_leave_no_files(self):
        def fail_write(stream):
            stream.write(b"partial")
            raise OSError("disk full")
        with self.app.app_context():
            file = FileStorage(stream=BytesIO(b"abc"), filename="sample.txt")
            with patch.object(file, "save", side_effect=fail_write):
                with self.assertRaises(OSError):
                    save_upload(1, file)
            with self.assertRaises(ValueError):
                save_upload(1, FileStorage(stream=BytesIO(b""), filename="empty.txt"))
        self.assertEqual(list(self.uploads.rglob("*.txt")), [])

    def test_upload_activity_failure_rolls_back_metadata_and_bytes(self):
        self.conn.fail_sql = "INSERT INTO project_activity"
        with patch("routes.project.fetchone", return_value={"id": 1, "is_private": 1}), \
             patch("routes.project.require_project_role"), self.assertRaises(RuntimeError):
            self.client.post("/project/1", data={"file": (BytesIO(b"hello"), "sample.txt")})
        self.assertEqual(self.conn.raw.execute("SELECT COUNT(*) FROM files").fetchone()[0], 0)
        self.assertEqual(list(self.uploads.rglob("*.txt")), [])

    def test_uncertain_upload_commit_retains_bytes_for_reconciliation(self):
        self.conn.fail_commit = True
        with patch("routes.project.fetchone", return_value={"id": 1, "is_private": 1}), \
             patch("routes.project.require_project_role"), \
             self.assertLogs(self.app.logger, level="ERROR"), self.assertRaises(RuntimeError):
            self.client.post("/project/1", data={"file": (BytesIO(b"hello"), "sample.txt")})
        self.assertEqual((self.uploads / "1" / "sample.txt").read_bytes(), b"hello")

    def test_same_name_upload_keeps_original_content(self):
        original = self.seed_file()
        with self.app.app_context():
            filename, _, _, _ = save_upload(1, FileStorage(stream=BytesIO(b"new"), filename="sample.txt"))
        self.assertEqual(filename, "sample_2.txt")
        self.assertEqual(original.read_text(), "keep me")

    def test_delete_failures_preserve_file_and_metadata(self):
        path = self.seed_file()
        for url, fail_sql in (("/files/1/delete", "DELETE FROM files"),
                              ("/project/1/delete", "DELETE FROM projects")):
            self.conn.fail_sql = fail_sql
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                self.client.post(url)
            self.assertTrue(path.exists())
            self.assertEqual(self.conn.raw.execute("SELECT COUNT(*) FROM files").fetchone()[0], 1)

    def test_commit_failure_does_not_delete_bytes_or_flash_success(self):
        path = self.seed_file()
        self.conn.fail_commit = True
        with self.assertLogs(self.app.logger, level="ERROR"), self.assertRaises(RuntimeError):
            self.client.post("/files/1/delete")
        self.assertTrue(path.exists())
        self.assertEqual(self.conn.raw.execute("SELECT COUNT(*) FROM files").fetchone()[0], 1)
        with self.client.session_transaction() as session:
            self.assertFalse(any(category == "success" for category, _ in session.get("_flashes", [])))

    def test_cleanup_runs_after_commit_and_disk_failure_is_reported(self):
        path = self.seed_file()
        def disk_failure(_):
            self.assertEqual(self.conn.commits, 1)
            raise PermissionError("file locked")
        with patch("utils.os.remove", side_effect=disk_failure), self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.post("/files/1/delete")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(path.exists())
        self.assertEqual(self.conn.raw.execute("SELECT COUNT(*) FROM files").fetchone()[0], 0)
        with self.client.session_transaction() as session:
            self.assertTrue(any("could not be removed" in text for _, text in session["_flashes"]))

    def test_successful_project_delete_removes_registered_files_only(self):
        path = self.seed_file()
        extra = path.parent / "unregistered.txt"
        extra.write_text("unrelated")
        response = self.client.post("/project/1/delete")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(path.exists())
        self.assertTrue(extra.exists())

    def test_invalid_project_lengths_do_not_replace_existing_languages(self):
        for field, value in (("title", "x" * 101), ("description", "x" * 2001), ("languages", "x" * 51)):
            data = {"title": "New title", "languages": "Rust", field: value}
            self.assertEqual(self.client.post("/project/1/edit", data=data).status_code, 302)
            self.assertEqual(self.conn.raw.execute("SELECT title FROM projects").fetchone()[0], "Original")

    def test_standalone_execute_still_commits(self):
        with self.app.app_context():
            execute("UPDATE projects SET title=%s WHERE id=%s", ("Standalone", 1))
        self.assertEqual(self.conn.commits, 1)


if __name__ == "__main__":
    unittest.main()
