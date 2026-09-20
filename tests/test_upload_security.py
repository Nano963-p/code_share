import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from config import Config


class UploadSecurityTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.multiple(Config, SECRET_KEY="s" * 48, DB_PASSWORD="test-only")
        self.config.start()
        self.addCleanup(self.config.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.uploads = self.root / "uploads"
        (self.uploads / "1").mkdir(parents=True)
        (self.uploads / "1" / "index.html").write_text("<script>alert(1)</script>")
        self.app = create_app()
        self.app.config.update(TESTING=True, UPLOAD_FOLDER=str(self.uploads))
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 2
        self.file = {
            "filepath": str(self.uploads / "1" / "index.html"),
            "filename": "index.html", "project_id": 1, "is_private": 1,
        }

    def request_file(self, url, role=None, private=True):
        self.file["is_private"] = private
        with patch("app.fetchone", return_value={"id": 10}), \
             patch("routes.project.fetchone", return_value=self.file), \
             patch("utils.get_project_role", return_value=role), \
             patch("routes.project.execute") as execute:
            response = self.client.get(url)
            response.get_data()
            response.close()
            return response, execute.call_count

    def test_private_files_block_nonmembers_on_both_routes(self):
        for url in ("/uploads/1/index.html", "/files/10/download"):
            with self.subTest(url=url):
                response, writes = self.request_file(url)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(writes, 0)

    def test_members_can_download_but_html_is_never_inline(self):
        for role in ("member", "admin", "owner"):
            for url in ("/uploads/1/index.html", "/files/10/download"):
                with self.subTest(role=role, url=url):
                    response, writes = self.request_file(url, role)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.headers["Content-Disposition"].startswith("attachment"))
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                    self.assertIn("no-store", response.headers["Cache-Control"])
                    self.assertEqual(writes, 1)

    def test_public_files_allow_logged_in_nonmembers(self):
        for url in ("/uploads/1/index.html", "/files/10/download"):
            self.assertEqual(self.request_file(url, private=False)[0].status_code, 200)

    def test_anonymous_download_requires_login(self):
        client = self.app.test_client()
        for url in ("/uploads/1/index.html", "/files/10/download"):
            response = client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith("/login"))

    def test_orphaned_upload_is_not_served(self):
        with patch("app.fetchone", return_value=None):
            self.assertEqual(self.client.get("/uploads/1/index.html").status_code, 404)

    def test_traversal_and_database_paths_outside_uploads_are_blocked(self):
        outside = self.root / "secret.txt"
        outside.write_text("private")
        self.assertEqual(self.client.get("/uploads/../secret.txt").status_code, 404)
        self.assertEqual(self.client.get("/uploads/..%5Csecret.txt").status_code, 404)
        self.file["filepath"] = str(outside)
        response, writes = self.request_file("/files/10/download", "member")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(writes, 0)

    def test_current_avatar_is_inline_with_image_mime(self):
        avatar = self.uploads / "avatars" / "2" / "photo.png"
        avatar.parent.mkdir(parents=True)
        avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
        with patch("app.fetchone", return_value={"id": 2}):
            response = self.client.get("/uploads/avatars/2/photo.png")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/png")
            self.assertTrue(response.headers["Content-Disposition"].startswith("inline"))
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            response.close()
        with patch("app.fetchone", return_value=None):
            self.assertEqual(self.client.get("/uploads/avatars/2/photo.png").status_code, 404)

    def test_startup_rejects_missing_or_weak_secrets(self):
        for secret in (None, "", "REDACTED"):
            with patch.object(Config, "SECRET_KEY", secret):
                with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
                    create_app()
        with patch.object(Config, "DB_PASSWORD", None):
            with self.assertRaisesRegex(RuntimeError, "DB_PASSWORD"):
                create_app()


if __name__ == "__main__":
    unittest.main()
