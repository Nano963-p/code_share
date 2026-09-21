from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from app import create_app
from config import Config
from routes.source import MAX_PREVIEW, render_preview, zip_index


class SourceTests(unittest.TestCase):
    def setUp(self):
        with patch.multiple(Config, SECRET_KEY="s" * 48, DB_PASSWORD="test-only"):
            self.app = create_app()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app.config.update(TESTING=True, UPLOAD_FOLDER=str(self.root))
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 7
        self.file = {"id": 10, "filename": "project.zip", "filepath": str(self.root / "project.zip"), "filesize": 100}
        with zipfile.ZipFile(self.file["filepath"], "w") as archive:
            archive.writestr("README.md", "# Welcome\n\n**Useful** project")
            archive.writestr("src/main.py", "print('hello')")
            archive.writestr("src/sub/example.js", "console.log('hello')")
        self.private = True
        for target, value in (("routes.source.current_user", {"id": 7, "username": "tester"}),
                              ("routes.source.fetchall", [self.file])):
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        def fetch(sql, params):
            if "FROM projects" in sql:
                return {"id": 1, "title": "Project", "is_private": self.private}
            return self.file if params == (10, 1) else None
        mock = patch("routes.source.fetchone", side_effect=fetch)
        mock.start()
        self.addCleanup(mock.stop)

    def get(self, path=""):
        with patch("utils.get_project_role", return_value="member"):
            return self.client.get("/project/1/source?file=10" + path)

    def test_zip_directory_navigation_and_automatic_readme(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertIn("<h1>Welcome</h1>", response.text)
        self.assertIn("src/", response.text)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        response = self.get("&path=src/")
        self.assertIn("main.py", response.text)
        self.assertIn("sub/", response.text)
        response = self.get("&path=src/main.py")
        self.assertIn('class="source-code"', response.text)
        self.assertIn("hello", response.text)

    def test_private_access_and_cross_project_file_id(self):
        with patch("utils.get_project_role", return_value=None):
            self.assertEqual(self.client.get("/project/1/source?file=10").status_code, 403)
        self.assertEqual(self.get("&path=../secret.txt").status_code, 400)
        with patch("utils.get_project_role", return_value="member"):
            self.assertEqual(self.client.get("/project/1/source?file=99").status_code, 404)
        self.assertEqual(self.app.test_client().get("/project/1/source").status_code, 302)

    def test_public_project_access(self):
        self.private = False
        response = self.client.get("/project/1/source?file=10")
        self.assertEqual(response.status_code, 200)

    def test_unsafe_archive_never_extracts(self):
        with zipfile.ZipFile(self.file["filepath"], "w") as archive:
            archive.writestr("../outside.py", "print('bad')")
        response = self.get()
        self.assertIn("unsafe paths", response.text)
        self.assertFalse((self.root.parent / "outside.py").exists())

    def test_code_is_escaped_and_markdown_is_sanitized(self):
        code, mode = render_preview("evil.html", b'<script>alert(1)</script>')
        self.assertNotIn("<script>", code)
        html, mode = render_preview("README.md", b'# Title\n<script>alert(1)</script>\n<a href="javascript:alert(1)">bad</a><img src=x onerror=alert(1)>')
        self.assertIn("<h1>Title</h1>", html)
        for unsafe in ("<script", "javascript:", "onerror", "<img"):
            self.assertNotIn(unsafe, html)

    def test_binary_large_and_compressed_bomb_are_bounded(self):
        for name, data in (("sample.pdf", b"%PDF"), ("x.py", b"\x00abc"), ("x.txt", b"a" * (MAX_PREVIEW + 1))):
            with self.assertRaises(ValueError):
                render_preview(name, data)
        with zipfile.ZipFile(self.file["filepath"], "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("bomb.txt", b"a" * (MAX_PREVIEW + 1))
        self.assertIn("compression limit", self.get("&path=bomb.txt").text)

    def test_plain_readme_selected_automatically(self):
        self.file.update(filename="README.md", filepath=str(self.root / "README.md"))
        Path(self.file["filepath"]).write_text("# Standalone README")
        with patch("utils.get_project_role", return_value="member"):
            response = self.client.get("/project/1/source")
        self.assertIn("<h1>Standalone README</h1>", response.text)


if __name__ == "__main__":
    unittest.main()
