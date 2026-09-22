"""Regression checks for credential revocation, permissions, and search pages."""
import unittest
from unittest.mock import MagicMock, patch

from app import create_app
from config import Config
from utils import login_required, session_fingerprint


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        with patch.multiple(Config, SECRET_KEY="s" * 48, DB_PASSWORD="test-only"):
            self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.app.add_url_rule("/session-check", "session_check", login_required(lambda: "OK"))
        self.client = self.app.test_client()
        self.credential = "old-password-hash"
        lookup = patch("utils.fetchone", side_effect=lambda *args: {"password_hash": self.credential})
        lookup.start()
        self.addCleanup(lookup.stop)
        self.sign_in(self.client)

    def sign_in(self, client):
        with self.app.app_context():
            fingerprint = session_fingerprint(self.credential)
        with client.session_transaction() as session:
            session["user_id"] = 7
            session["credential_fingerprint"] = fingerprint

    def test_password_change_revokes_both_browsers_after_commit(self):
        other = self.app.test_client()
        self.sign_in(other)
        self.assertEqual(other.get("/session-check").status_code, 200)
        connection = MagicMock()
        connection.commit.side_effect = lambda: setattr(self, "credential", "new-password-hash")
        with patch("db.get_conn", return_value=connection), \
             patch("routes.profile.current_user", return_value={"id": 7}), \
             patch("routes.profile.fetchone", side_effect=[{"id": 7}, None, {"password_hash": self.credential}]), \
             patch("routes.profile.verify_password", return_value=True), \
             patch("routes.profile.hash_password", return_value="new-password-hash"):
            response = self.client.post("/profile/edit", data={"username": "tester", "email": "test@example.com",
                "current_password": "old-password", "new_password": "new-password", "confirm_password": "new-password"})
        self.assertTrue(response.location.endswith("/login"))
        for client in (self.client, other):
            self.assertEqual(client.get("/session-check").status_code, 302)
            with client.session_transaction() as session:
                self.assertNotIn("user_id", session)
        self.sign_in(other)
        self.assertEqual(other.get("/session-check").status_code, 200)

    def test_failed_password_update_keeps_session_valid(self):
        with patch("db.get_conn", return_value=MagicMock()), \
             patch("routes.profile.current_user", return_value={"id": 7}), \
             patch("routes.profile.fetchone", side_effect=[{"id": 7}, None, {"password_hash": self.credential}]), \
             patch("routes.profile.verify_password", return_value=True), \
             patch("routes.profile.execute", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                self.client.post("/profile/edit", data={"username": "tester", "email": "test@example.com",
                    "current_password": "old-password", "new_password": "new-password", "confirm_password": "new-password"})
        self.assertEqual(self.client.get("/session-check").status_code, 200)

    def test_legacy_tampered_and_deleted_account_sessions_are_rejected(self):
        for fingerprint in (None, "tampered"):
            with self.client.session_transaction() as session:
                session["user_id"] = 7
                session["credential_fingerprint"] = fingerprint
            self.assertEqual(self.client.get("/session-check").status_code, 302)
        self.sign_in(self.client)
        with patch("utils.fetchone", return_value=None):
            self.assertEqual(self.client.get("/session-check").status_code, 302)

    def test_login_and_signup_create_valid_sessions(self):
        for endpoint in ("/login", "/signup"):
            with patch("routes.auth.fetchone", return_value={"id": 7, "password_hash": self.credential} if endpoint == "/login" else None), \
                 patch("routes.auth.verify_password", return_value=True), \
                 patch("routes.auth.hash_password", return_value=self.credential), \
                 patch("routes.auth.execute", return_value=7):
                self.client.post(endpoint, data={"username": "tester", "email": "test@example.com",
                    "password": "password", "confirm_password": "password"})
            self.assertEqual(self.client.get("/session-check").status_code, 200)

    def test_project_contribution_forms_follow_membership(self):
        project = {"id": 1, "title": "Project", "description": "", "created_at": "", "is_private": 0,
                   "owner_id": 8, "owner_username": "owner", "status": "active"}
        for role in (None, "member", "admin", "owner"):
            with self.subTest(role=role), patch("routes.project.current_user", return_value={"id": 7, "username": "tester"}), \
                 patch("routes.project.fetchone", side_effect=[project, {"c": 0}, None, None, {"c": 0}]), \
                 patch("routes.project.fetchall", return_value=[]), \
                 patch("routes.project.is_project_owner", return_value=role == "owner"), \
                 patch("routes.project.get_project_role", return_value=role):
                response = self.client.get("/project/1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual('class="upload"' in response.text, role is not None)
            self.assertEqual('class="comment-form"' in response.text, role is not None)
        with patch("db.get_conn", return_value=MagicMock()), \
             patch("routes.project.current_user", return_value={"id": 7}), \
             patch("routes.project.fetchone", return_value=project), \
             patch("utils.get_project_role", return_value=None), \
             patch("routes.project.execute") as execute:
            self.assertEqual(self.client.post("/project/1", data={"message": "Blocked"}).status_code, 403)
            execute.assert_not_called()

    def test_search_pages_preserve_query_and_have_no_overlap(self):
        projects = [{"id": n, "title": f"Project {n}", "description": "", "owner": "tester", "owner_id": 7,
                     "stars": 0, "tags": "python"} for n in range(65)]
        def query(sql, params):
            self.assertIn("p.is_private = 0", sql)
            self.assertIn("pm.user_id = %s", sql)
            self.assertIn("p.id DESC", sql)
            limit, offset = params[-2:]
            return projects[offset:offset + limit]
        with patch("app.current_user", return_value={"id": 7, "username": "tester"}), \
             patch("app.fetchall", side_effect=query), patch("app.fetchone", return_value=None):
            for term in ("python", "%23python"):
                first = self.client.get(f"/search?q={term}")
                second = self.client.get(f"/search?q={term}&page=2")
                last = self.client.get(f"/search?q={term}&page=3")
                empty = self.client.get(f"/search?q={term}&page=4")
                self.assertIn("Project 29</h3>", first.text)
                self.assertNotIn("Project 30</h3>", first.text)
                self.assertIn("Project 30</h3>", second.text)
                self.assertIn("page=2", first.text)
                self.assertIn("q=" + term, first.text)
                self.assertIn("Previous", second.text)
                self.assertNotIn(">Next</a>", last.text)
                self.assertIn("Previous", empty.text)
            for page in ("0", "-1", "invalid", "1000001"):
                self.assertEqual(self.client.get(f"/search?q=python&page={page}").status_code, 400)


if __name__ == "__main__":
    unittest.main()
