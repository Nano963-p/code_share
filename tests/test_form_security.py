from io import BytesIO
from pathlib import Path
import re
import time
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from config import Config


class FormSecurityTests(unittest.TestCase):
    def setUp(self):
        with patch.multiple(Config, SECRET_KEY="s" * 48, DB_PASSWORD="test-only",
                            RATELIMIT_STORAGE_URI="memory://",
                            LOGIN_RATE_LIMIT="5 per minute;30 per hour"):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        connection = patch("db.get_conn", return_value=MagicMock())
        connection.start()
        self.addCleanup(connection.stop)

    def token(self, client=None):
        response = (client or self.client).get("/login")
        return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)

    def test_all_post_routes_reject_missing_token_before_handler(self):
        for rule in self.app.url_map.iter_rules():
            if "POST" not in rule.methods:
                continue
            url = re.sub(r"<int:\w+>", "1", rule.rule)
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 400)
                self.assertIn("Refresh the page", response.text)

    def test_wrong_foreign_and_expired_tokens_rejected(self):
        token = self.token()
        foreign = self.token(self.app.test_client())
        for value in ("invalid", foreign):
            self.assertEqual(self.client.post("/login", data={"csrf_token": value}).status_code, 400)
        self.app.config["WTF_CSRF_TIME_LIMIT"] = -1
        self.assertEqual(self.client.post("/login", data={"csrf_token": token}).status_code, 400)

    def test_valid_login_rotates_session_and_old_token(self):
        token = self.token()
        with self.client.session_transaction() as session:
            session["old_value"] = "discard"
        with patch("routes.auth.fetchone", return_value={"id": 7, "password_hash": "hash"}), \
             patch("routes.auth.verify_password", return_value=True):
            response = self.client.post("/login", data={"csrf_token": token, "username": "alice", "password": "valid"})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], 7)
            self.assertNotIn("old_value", session)
        self.assertEqual(self.client.post("/logout", data={"csrf_token": token}).status_code, 400)
        self.assertEqual(self.client.get("/logout").status_code, 405)
        response = self.client.post("/logout", data={"csrf_token": self.token()})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_valid_signup_is_allowed(self):
        with patch("routes.auth.fetchone", return_value=None), \
             patch("routes.auth.execute", return_value=7), \
             patch("routes.auth.hash_password", return_value="hash"):
            response = self.client.post("/signup", data={"csrf_token": self.token(),
                "username": "alice", "email": "alice@example.com", "password": "testpass",
                "confirm_password": "testpass"})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], 7)

    def test_limit_blocks_before_password_check_and_cannot_spoof_ip(self):
        token = self.token()
        with patch("routes.auth.fetchone", return_value=None) as lookup:
            for _ in range(5):
                response = self.client.post("/login", data={"csrf_token": token})
                self.assertEqual(response.status_code, 302)
            for headers in ({}, {"X-Forwarded-For": "198.51.100.10"}):
                response = self.client.post("/login", data={"csrf_token": token}, headers=headers)
                self.assertEqual(response.status_code, 429)
                self.assertGreater(int(response.headers["Retry-After"]), 0)
            self.assertEqual(lookup.call_count, 5)
            self.assertEqual(self.client.get("/login").status_code, 200)
            other = self.client.post("/login", data={"csrf_token": token},
                                     environ_overrides={"REMOTE_ADDR": "198.51.100.20"})
            self.assertEqual(other.status_code, 302)

    def test_valid_multipart_and_project_action_reach_handlers(self):
        token = self.token()
        with self.client.session_transaction() as session:
            session["user_id"] = 7
        with patch("routes.project.current_user", return_value={"id": 7}), \
             patch("routes.project.fetchone", return_value={"id": 1, "is_private": 1}), \
             patch("routes.project.require_project_role"), \
             patch("routes.project.save_upload", return_value=("a.txt", "uploads/1/a.txt", 1, "digest")), \
             patch("routes.project.execute", return_value=10) as execute, \
             patch("routes.project.log_activity"):
            response = self.client.post("/project/1", data={"csrf_token": token,
                "file": (BytesIO(b"a"), "a.txt")}, content_type="multipart/form-data")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(execute.call_count, 1)
            response = self.client.post("/project/1/like", data={"csrf_token": token})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(execute.call_count, 2)

    def test_minute_limit_recovers_and_hour_limit_still_applies(self):
        token = self.token()
        now = time.time()
        with patch("routes.auth.fetchone", return_value=None):
            for minute in range(6):
                with patch("time.time", return_value=now + minute * 61):
                    for _ in range(5):
                        self.assertEqual(self.client.post("/login", data={"csrf_token": token}).status_code, 302)
                    self.assertEqual(self.client.post("/login", data={"csrf_token": token}).status_code, 429)
            with patch("time.time", return_value=now + 366):
                self.assertEqual(self.client.post("/login", data={"csrf_token": token}).status_code, 429)

    def test_every_post_template_form_has_token(self):
        # Check all forms, including conditional and multi-line form markup.
        for path in Path(self.app.template_folder).rglob("*.html"):
            source = path.read_text(encoding="utf-8")
            for form in re.findall(r"<form\b.*?</form>", source, re.S | re.I):
                if re.search(r'method="POST"', form, re.I):
                    with self.subTest(template=str(path)):
                        self.assertIn('name="csrf_token"', form)
                        self.assertIn("csrf_token()", form)


if __name__ == "__main__":
    unittest.main()
