import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

import manage_db as admin


class DatabaseAdminTests(unittest.TestCase):
    def archive(self, path, entries, checksums=None):
        metadata = {"format": 1, "sha256": checksums or {
            name: hashlib.sha256(value).hexdigest() for name, value in entries.items()}}
        with zipfile.ZipFile(path, "w") as archive:
            for name, value in entries.items():
                archive.writestr(name, value)
            archive.writestr("manifest.json", json.dumps(metadata))

    def test_database_names_reject_system_and_sql_injection(self):
        for name in ("mysql", "sys", "information_schema", "test;DROP DATABASE x", "../data", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                admin.identifier(name)

    def test_archive_rejects_corruption_and_traversal_before_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "backup.zip"
            self.archive(source, {"database.sql": b"test"}, {"database.sql": "wrong"})
            with zipfile.ZipFile(source) as archive, self.assertRaisesRegex(ValueError, "checksum"):
                admin.inspect_archive(archive)
            for name in ("uploads/../outside", "uploads/C:/outside", "uploads/..\\outside"):
                self.archive(source, {"database.sql": b"test", name: b"bad"})
                with zipfile.ZipFile(source) as archive, self.assertRaises(ValueError):
                    admin.inspect_archive(archive)

    def test_restore_refuses_existing_directory_without_connecting(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(admin, "connect") as connect:
            with self.assertRaisesRegex(ValueError, "new upload directory"):
                admin.restore("not-needed.zip", "recovery_test", folder)
            connect.assert_not_called()

    def test_restore_refuses_configured_database_before_creating_target(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(admin, "create_database") as create:
            source = Path(folder) / "backup.zip"
            self.archive(source, {"database.sql": b"test"})
            with self.assertRaisesRegex(ValueError, "configured"):
                admin.restore(source, admin.Config.DB_NAME, Path(folder) / "uploads")
            create.assert_not_called()

    def test_migration_history_refuses_changed_or_failed_revisions(self):
        first = admin.migration_files()[0]
        with self.assertRaisesRegex(ValueError, "checksum"):
            admin.validate_history({first.stem: ("invalid", "applied")})
        for state in ("applying", "failed"):
            with self.assertRaisesRegex(ValueError, state):
                admin.validate_history({first.stem: (admin.digest(first), state)})

    def test_migration_has_no_reset_or_database_selection(self):
        source = admin.migration_files()[0].read_text()
        self.assertNotRegex(source, r"(?im)^\s*(DROP|USE|CREATE DATABASE)\b")


@unittest.skipUnless(os.getenv("RUN_MYSQL_ADMIN_TESTS") == "1", "Opt-in disposable MySQL recovery test")
class MySQLRecoveryTests(unittest.TestCase):
    def test_fresh_migration_adoption_backup_and_restore(self):
        token = uuid.uuid4().hex[:12]
        source_db, recovery_db = "code_share_test_" + token, "code_share_restore_" + token
        created = []
        with tempfile.TemporaryDirectory(dir=admin.ROOT / ".venv") as folder:
            base = Path(folder)
            uploads = base / "uploads"
            uploads.mkdir()
            path = uploads / "1" / "example.txt"
            path.parent.mkdir()
            path.write_bytes(b"verified recovery content\x00\xff")
            try:
                admin.create_database(source_db)
                created.append(source_db)
                admin.migrate(source_db)
                admin.migrate(source_db)  # Idempotent.
                with admin.connect(source_db) as conn:
                    admin.rows(conn, "INSERT INTO users(username,email,password_hash) VALUES ('recovery_test','recovery@example.com','test-only')")
                    admin.rows(conn, "INSERT INTO projects(owner_id,title) VALUES (1,'Recovery fixture')")
                    admin.rows(conn, "INSERT INTO files(project_id,uploaded_by,filename,filepath,filesize) VALUES (1,1,'example.txt',%s,%s)", (str(path), path.stat().st_size))
                    before = admin.table_counts(conn)
                    # Simulate the existing, pre-migrations deployment.
                    admin.rows(conn, "DROP TABLE schema_migrations")
                with self.assertRaisesRegex(ValueError, "no migration history"):
                    admin.migrate(source_db)
                with admin.connect(source_db) as conn:
                    admin.rows(conn, "ALTER TABLE users ADD COLUMN recovery_probe INT")
                with self.assertRaisesRegex(ValueError, "differs"):
                    admin.migrate(source_db, baseline=True)
                with admin.connect(source_db) as conn:
                    admin.rows(conn, "ALTER TABLE users DROP COLUMN recovery_probe")
                admin.migrate(source_db, baseline=True)
                with admin.connect(source_db) as conn:
                    self.assertEqual(admin.table_counts(conn), before)
                backup = base / "snapshot.zip"
                admin.backup(source_db, uploads, backup)
                recovery_uploads = base / "restored"
                # The helper only creates this exact new target; cleanup is scoped to it.
                created.append(recovery_db)
                admin.restore(backup, recovery_db, recovery_uploads)
                self.assertEqual((recovery_uploads / "1" / "example.txt").read_bytes(), path.read_bytes())
                with admin.connect(recovery_db) as conn:
                    self.assertEqual(admin.table_counts(conn), before)
                    stored = admin.rows(conn, "SELECT filepath FROM files WHERE id=1")[0][0]
                    self.assertEqual((admin.ROOT / stored).resolve(), recovery_uploads / "1" / "example.txt")
                    self.assertEqual(admin.rows(conn, "SELECT role FROM project_members WHERE user_id=1")[0][0], "owner")
                with admin.connect(source_db) as conn:
                    self.assertEqual(admin.table_counts(conn), before)
                    self.assertEqual(admin.rows(conn, "SELECT filepath FROM files WHERE id=1")[0][0], str(path))
                # MySQL DDL cannot be rolled back. Record partial failure and
                # block retries instead of pretending the migration was atomic.
                migrations = base / "migrations"
                shutil.copytree(admin.MIGRATIONS, migrations)
                (migrations / "0002_failure.sql").write_text(
                    "CREATE TABLE recovery_partial_probe(id INT);\nINVALID SQL;\n")
                with patch.object(admin, "MIGRATIONS", migrations):
                    with self.assertRaises(admin.subprocess.CalledProcessError):
                        admin.migrate(recovery_db)
                    with admin.connect(recovery_db) as conn:
                        self.assertEqual(admin.history(conn)["0002_failure"][1], "failed")
                    with self.assertRaisesRegex(ValueError, "failed"):
                        admin.migrate(recovery_db)
            finally:
                with admin.connect() as conn:
                    for database in reversed(created):
                        if not database.endswith(token):
                            raise AssertionError("Unsafe cleanup target")
                        admin.rows(conn, f"DROP DATABASE IF EXISTS `{database}`")


if __name__ == "__main__":
    unittest.main()
