from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image
from app import create_app
from config import Config


class ProfilePhotoTests(unittest.TestCase):
    def setUp(self):
        with patch.multiple(Config, SECRET_KEY="s" * 48, DB_PASSWORD="test-only"):
            self.app = create_app()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / "avatars/7/old.png"
        self.old.parent.mkdir(parents=True)
        Image.new("RGB", (8, 8)).save(self.old)
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, UPLOAD_FOLDER=str(self.root))
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 7
        self.conn = MagicMock()
        for target, value in (("db.get_conn", self.conn),
                              ("routes.profile.current_user", {"id": 7, "profile_image": "avatars/7/old.png"}),
                              ("routes.profile.fetchone", None)):
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def photo_data(self):
        stream = BytesIO()
        Image.new("RGB", (10, 10)).save(stream, format="JPEG")
        stream.seek(0)
        return {"username": "tester", "email": "tester@example.com", "profile_image": (stream, "photo.jpg")}

    def test_replacement_commits_before_deleting_old_image(self):
        self.conn.commit.side_effect = lambda: self.assertTrue(self.old.exists())
        response = self.client.post("/profile/edit", data=self.photo_data())
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.old.exists())
        paths = list(self.root.rglob("*.png"))
        self.assertEqual(len(paths), 1)
        with Image.open(paths[0]) as image:
            self.assertEqual(image.format, "PNG")

    def test_statement_failure_preserves_old_and_removes_new(self):
        with patch("routes.profile.execute", side_effect=RuntimeError("SQL failure")), self.assertRaises(RuntimeError):
            self.client.post("/profile/edit", data=self.photo_data())
        self.assertEqual(list(self.root.rglob("*.png")), [self.old])
        self.conn.rollback.assert_called_once()

    def test_commit_failure_preserves_both_for_reconciliation(self):
        self.conn.commit.side_effect = RuntimeError("Connection lost")
        with self.assertLogs(self.app.logger, level="ERROR"), self.assertRaises(RuntimeError):
            self.client.post("/profile/edit", data=self.photo_data())
        self.assertTrue(self.old.exists())
        self.assertEqual(len(list(self.root.rglob("*.png"))), 2)

    def test_remove_photo_does_not_delete_before_commit(self):
        self.conn.commit.side_effect = lambda: self.assertTrue(self.old.exists())
        response = self.client.post("/profile/edit", data={"username": "tester", "email": "test@example.com", "remove_profile_image": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.old.exists())

    def test_fake_image_is_rejected_without_update(self):
        with patch("routes.profile.execute") as execute:
            response = self.client.post("/profile/edit", data={"username": "tester", "email": "test@example.com", "profile_image": (BytesIO(b"<script>bad</script>"), "fake.png")})
            self.assertEqual(response.status_code, 302)
            execute.assert_not_called()
        self.assertEqual(list(self.root.rglob("*.png")), [self.old])


if __name__ == "__main__":
    unittest.main()
