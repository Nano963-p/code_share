"""Offline migration and recovery commands. Never reset an existing database."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

import mysql.connector
from config import Config

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "migrations"
HISTORY = "schema_migrations"


def identifier(value):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", value):
        raise ValueError("Database names must start with a letter and contain only letters, digits, underscores.")
    if value.lower() in {"mysql", "sys", "information_schema", "performance_schema"}:
        raise ValueError("System databases are not allowed.")
    return value


def connect(database=None):
    return mysql.connector.connect(host=Config.DB_HOST, port=Config.DB_PORT,
        user=Config.DB_USER, password=Config.DB_PASSWORD, database=database, autocommit=True)


def rows(conn, sql, params=()):
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.with_rows else []
    finally:
        cursor.close()


def tables(conn):
    return [row[0] for row in rows(conn, "SHOW FULL TABLES WHERE Table_type='BASE TABLE'")]


def digest(path):
    with open(path, "rb") as stream:
        return stream_digest(stream)


def stream_digest(stream):
    checksum = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        checksum.update(chunk)
    return checksum.hexdigest()


def mysql_tool(name):
    directory = os.getenv("MYSQL_BIN_DIR")
    candidates = ([Path(directory) / (name + ".exe"), Path(directory) / name] if directory else [])
    installed = shutil.which(name)
    if installed:
        candidates.append(Path(installed))
    candidates.append(Path("C:/Program Files/MySQL/MySQL Server 8.0/bin") / (name + ".exe"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise ValueError(f"Cannot find {name}; set MYSQL_BIN_DIR to your MySQL bin directory.")


@contextmanager
def client_options():
    # Credentials are not passed on the command line or placed in the backup.
    with tempfile.TemporaryDirectory(prefix="code-share-mysql-") as directory:
        path = Path(directory) / "client.cnf"
        def quote(value):
            return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r') + '"'
        path.write_text("[client]\n" + "\n".join(f"{key}={quote(value)}" for key, value in {
            "host": Config.DB_HOST, "port": Config.DB_PORT,
            "user": Config.DB_USER, "password": Config.DB_PASSWORD or "",
        }.items()) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        yield f"--defaults-extra-file={path}"


def run_sql(database, sql_path):
    with client_options() as options, open(sql_path, "rb") as source:
        subprocess.run([mysql_tool("mysql"), options, "--default-character-set=utf8mb4",
                        "--binary-mode", database], stdin=source, check=True)


def signature(conn):
    """Compare column/index/FK/check definitions and stored program bodies.

    Ignore counters, definers, formatting, and database-default collation choices.
    """
    def normalize(sql):
        sql = re.sub(r"DEFINER\s*=\s*`[^`]*`@`[^`]*`", "", sql, flags=re.I)
        sql = re.sub(r"AUTO_INCREMENT=\d+", "", sql, flags=re.I)
        sql = re.sub(r"/\*.*?\*/|--[^\n]*", "", sql, flags=re.S)
        sql = re.sub(r"DEFAULT CHARSET=utf8mb4\b|CHARACTER SET utf8mb4\b|COLLATE[=\s]+utf8mb4_\w+", "", sql, flags=re.I)
        return re.sub(r"\s+", "", sql).lower()
    result = {}
    for name in sorted(tables(conn)):
        if name != HISTORY:
            sql = rows(conn, f"SHOW CREATE TABLE `{name}`")[0][1]
            # Column/index ordering does not affect the application's named queries.
            lines = sql.splitlines()
            result["table:" + name] = sorted(normalize(line.rstrip(",")) for line in lines[1:-1]) + [normalize(lines[-1])]
    for name, in rows(conn, "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()"):
        result["trigger:" + name] = normalize(rows(conn, f"SHOW CREATE TRIGGER `{name}`")[0][2])
    for name, kind in rows(conn, "SELECT ROUTINE_NAME, ROUTINE_TYPE FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE()"):
        result[kind.lower() + ":" + name] = normalize(rows(conn, f"SHOW CREATE {kind} `{name}`")[0][2])
    return result


def history(conn):
    if HISTORY not in tables(conn):
        return {}
    return {version: (checksum, state) for version, checksum, state in rows(
        conn, f"SELECT version, checksum, state FROM {HISTORY} ORDER BY version")}


def migration_files():
    return sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def validate_history(applied):
    files = {p.stem: p for p in migration_files()}
    for version, (checksum, state) in applied.items():
        if version not in files or digest(files[version]) != checksum:
            raise ValueError(f"Migration checksum mismatch or unknown version: {version}")
        if state != "applied":
            raise ValueError(f"Migration {version} is {state}; inspect the schema and restore to a new database before retrying.")


@contextmanager
def migration_lock(conn, database):
    lock = "code_share_migrate_" + hashlib.sha256(database.encode()).hexdigest()[:40]
    if rows(conn, "SELECT GET_LOCK(%s, 0)", (lock,))[0][0] != 1:
        raise ValueError("Another migration is running.")
    try:
        yield
    finally:
        rows(conn, "SELECT RELEASE_LOCK(%s)", (lock,))


def create_history(conn):
    rows(conn, f"""CREATE TABLE IF NOT EXISTS {HISTORY} (
        version VARCHAR(100) PRIMARY KEY, checksum CHAR(64) NOT NULL,
        state VARCHAR(16) NOT NULL, applied_at TIMESTAMP NULL) ENGINE=InnoDB""")


def migrate(database, baseline=False):
    with connect(database) as conn, migration_lock(conn, database):
        applied = history(conn)
        validate_history(applied)
        existing = set(tables(conn)) - {HISTORY}
        if baseline:
            if applied:
                raise ValueError("Database already has migration history; use migrate.")
            expected = json.loads((MIGRATIONS / "0001_schema.json").read_text())
            if signature(conn) != expected:
                raise ValueError("Existing schema differs from the initial migration; baseline refused. Review schema differences first.")
            create_history(conn)
            initial = migration_files()[0]
            rows(conn, f"INSERT INTO {HISTORY} VALUES (%s,%s,'applied',CURRENT_TIMESTAMP)", (initial.stem, digest(initial)))
            print("Recorded initial baseline; existing application tables and data were untouched.")
            return
        if existing and not applied:
            raise ValueError("Existing database has no migration history. Back it up, then use baseline.")
        create_history(conn)
        for path in migration_files():
            if path.stem in applied:
                continue
            rows(conn, f"INSERT INTO {HISTORY} VALUES (%s,%s,'applying',NULL)", (path.stem, digest(path)))
            try:
                run_sql(database, path)
            except Exception:
                rows(conn, f"UPDATE {HISTORY} SET state='failed' WHERE version=%s", (path.stem,))
                raise
            rows(conn, f"UPDATE {HISTORY} SET state='applied', applied_at=CURRENT_TIMESTAMP WHERE version=%s", (path.stem,))
            print("Applied", path.stem)


def create_database(database):
    with connect() as conn:
        # Deliberately no IF NOT EXISTS: never reuse a recovery target.
        rows(conn, f"CREATE DATABASE `{identifier(database)}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")


def table_counts(conn):
    return {name: rows(conn, f"SELECT COUNT(*) FROM `{name}`")[0][0] for name in tables(conn)}


def backup(database, uploads, output):
    uploads, output = Path(uploads).resolve(), Path(output).resolve()
    if not uploads.is_dir() or output.exists():
        raise ValueError("Uploads must exist, and the backup output must not already exist.")
    if output.is_relative_to(uploads):
        raise ValueError("Backup output must be outside the upload directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="code-share-backup-") as temp:
        sql = Path(temp) / "database.sql"
        with connect(database) as conn:
            metadata = {"format": 1, "database": database, "created_at": datetime.now(timezone.utc).isoformat(),
                        "counts": table_counts(conn), "schema": signature(conn)}
            metadata["file_paths"] = {}
            if "files" in tables(conn):
                for file_id, stored in rows(conn, "SELECT id, filepath FROM files"):
                    path = (ROOT / stored).resolve()
                    if not path.is_relative_to(uploads) or not path.is_file():
                        raise ValueError(f"File record {file_id} is missing or outside upload storage; repair it before backup.")
                    metadata["file_paths"][str(file_id)] = path.relative_to(uploads).as_posix()
            if "users" in tables(conn):
                for user_id, stored in rows(conn, "SELECT id, profile_image FROM users WHERE profile_image IS NOT NULL"):
                    path = (uploads / stored).resolve()
                    if not path.is_relative_to(uploads) or not path.is_file():
                        raise ValueError(f"Profile photo for user {user_id} is missing; repair it before backup.")
        with client_options() as options, sql.open("wb") as destination:
            subprocess.run([mysql_tool("mysqldump"), options, "--single-transaction", "--quick",
                "--routines", "--triggers", "--hex-blob", "--no-tablespaces", "--set-gtid-purged=OFF",
                "--default-character-set=utf8mb4", database], stdout=destination, check=True)
        entries = {"database.sql": sql}
        for path in uploads.rglob("*"):
            if path.is_symlink() or not path.resolve().is_relative_to(uploads):
                raise ValueError("Symlinks or junctions in uploads are not supported.")
            if path.is_file():
                entries["uploads/" + path.relative_to(uploads).as_posix()] = path
        metadata["sha256"] = {name: digest(path) for name, path in entries.items()}
        # Publish only complete archives; failed creation leaves no valid-looking backup.
        partial = output.with_name(output.name + ".partial")
        with partial.open("xb") as target:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, path in entries.items():
                    archive.write(path, name)
                archive.writestr("manifest.json", json.dumps(metadata, indent=2))
        # A hard link publishes the complete file without overwriting a target
        # another process created while the backup was running.
        os.link(partial, output)
        partial.unlink()
    print("Backup created:", output)


def inspect_archive(archive):
    names = archive.namelist()
    if len(names) != len(set(name.casefold() for name in names)) or "manifest.json" not in names:
        raise ValueError("Invalid backup manifest or duplicate archive paths.")
    metadata = json.loads(archive.read("manifest.json"))
    if metadata.get("format") != 1 or "database.sql" not in metadata.get("sha256", {}):
        raise ValueError("Unsupported backup format.")
    if set(names) != set(metadata["sha256"]) | {"manifest.json"}:
        raise ValueError("Backup file list does not match manifest.")
    for name, expected in metadata["sha256"].items():
        parts = name.split("/")
        if "\\" in name or ":" in name or any(p in {"", ".", ".."} or p.endswith((" ", ".")) for p in parts):
            raise ValueError("Unsafe archive path.")
        if name != "database.sql" and (len(parts) < 2 or parts[0] != "uploads"):
            raise ValueError("Unexpected backup entry.")
        with archive.open(name) as stream:
            if stream_digest(stream) != expected:
                raise ValueError(f"Backup checksum mismatch: {name}")
    for file_id, relative in metadata.get("file_paths", {}).items():
        if not file_id.isdecimal() or "uploads/" + relative not in metadata["sha256"]:
            raise ValueError("Invalid file path mapping in backup.")
    return metadata


def restore(source, database, uploads):
    uploads = Path(uploads).resolve()
    if uploads.exists():
        raise ValueError("Restore requires a new upload directory.")
    with zipfile.ZipFile(source) as archive:
        metadata = inspect_archive(archive)
        if database.lower() == Config.DB_NAME.lower():
            raise ValueError("Restore cannot target the configured application database.")
        # Verify everything before creating a target. No existing database is dropped.
        create_database(database)
        uploads.mkdir(parents=True, exist_ok=False)
        with tempfile.TemporaryDirectory(prefix="code-share-restore-") as temp:
            sql = Path(temp) / "database.sql"
            with archive.open("database.sql") as src, sql.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            run_sql(database, sql)
        for name in metadata["sha256"]:
            if not name.startswith("uploads/"):
                continue
            path = uploads.joinpath(*name.split("/")[1:])
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as src, path.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            if digest(path) != metadata["sha256"][name]:
                raise ValueError("Restored upload checksum mismatch.")
        with connect(database) as conn:
            actual_counts, actual_schema = table_counts(conn), signature(conn)
            count_diff = [name for name in set(actual_counts) | set(metadata["counts"])
                          if actual_counts.get(name) != metadata["counts"].get(name)]
            schema_diff = [name for name in set(actual_schema) | set(metadata["schema"])
                           if actual_schema.get(name) != metadata["schema"].get(name)]
            if count_diff or schema_diff:
                raise ValueError(f"Restore verification failed. Row counts: {count_diff}; schema: {schema_diff}")
            # File records historically store paths relative to the app root.
            # Rebase these to the new recovery directory without touching the source.
            conn.autocommit = False
            for file_id, relative in metadata.get("file_paths", {}).items():
                stored = os.path.relpath(uploads / relative, ROOT).replace("\\", "/")
                rows(conn, "UPDATE files SET filepath=%s WHERE id=%s", (stored, int(file_id)))
            conn.commit()
    print(f"Restore verified: {database}; uploads: {uploads}. Application configuration was not changed.")


def orphan_inventory(database, uploads):
    uploads = Path(uploads).resolve()
    if not uploads.is_dir():
        raise ValueError("Upload directory does not exist.")
    with connect(database) as conn:
        references = {(ROOT / stored).resolve() for stored, in rows(conn, "SELECT filepath FROM files")}
        references.update((uploads / stored).resolve() for stored, in rows(
            conn, "SELECT profile_image FROM users WHERE profile_image IS NOT NULL"))
    files = []
    for path in uploads.rglob("*"):
        if path.is_symlink() or not path.resolve().is_relative_to(uploads):
            raise ValueError("Symlinks/junctions in upload storage must be inspected manually.")
        if path.is_file() and path.resolve() not in references:
            files.append(path)
    return sorted(files), sorted(path for path in references if not path.is_file())


def quarantine_orphans(database, uploads, destination=None):
    uploads = Path(uploads).resolve()
    orphans, missing = orphan_inventory(database, uploads)
    print(f"Unreferenced files: {len(orphans)}; missing referenced files: {len(missing)}")
    for path in orphans:
        print("Unreferenced:", path.relative_to(uploads))
    for path in missing:
        print("Missing:", path)
    if destination is None:
        print("Dry run only; no files moved.")
        return
    if missing:
        raise ValueError("Repair missing references before quarantining possible recovery copies.")
    destination = Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(uploads):
        raise ValueError("Quarantine must be a new directory outside upload storage.")
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {"database": database, "source": str(uploads), "files": {
        path.relative_to(uploads).as_posix(): digest(path) for path in orphans}}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for path in orphans:
        target = destination / "files" / path.relative_to(uploads)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    print("Moved to recoverable quarantine:", destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "init", "migrate", "baseline", "backup", "restore", "orphans"):
        sub = commands.add_parser(command)
        sub.add_argument("--database", required=command in {"init", "restore"}, default=Config.DB_NAME, type=identifier)
        if command in {"migrate", "baseline", "backup"}:
            sub.add_argument("--maintenance-confirmed", action="store_true", required=True,
                             help="Confirm all application workers and other writers are stopped.")
        if command == "backup":
            sub.add_argument("--uploads", default=Config.UPLOAD_FOLDER)
            sub.add_argument("--output", required=True)
        if command == "restore":
            sub.add_argument("--backup", required=True)
            sub.add_argument("--uploads", required=True)
        if command == "orphans":
            sub.add_argument("--uploads", default=Config.UPLOAD_FOLDER)
            sub.add_argument("--quarantine", help="Move unreferenced files into this NEW directory; omit for dry run.")
            sub.add_argument("--maintenance-confirmed", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "init":
            create_database(args.database)
            migrate(args.database)
        elif args.command in {"migrate", "baseline"}:
            migrate(args.database, baseline=args.command == "baseline")
        elif args.command == "backup":
            backup(args.database, args.uploads, args.output)
        elif args.command == "restore":
            restore(args.backup, args.database, args.uploads)
        elif args.command == "orphans":
            if args.quarantine and not args.maintenance_confirmed:
                raise ValueError("Stop all writers and pass --maintenance-confirmed before moving files.")
            quarantine_orphans(args.database, args.uploads, args.quarantine)
        else:
            with connect(args.database) as conn:
                applied = history(conn)
                validate_history(applied)
                for path in migration_files():
                    print(path.stem, applied.get(path.stem, (None, "pending"))[1])
                if tables(conn) and not applied:
                    print("Existing database: backup and baseline required before migration.")
    except (ValueError, OSError, mysql.connector.Error, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Error: {exc}\nNo existing database was reset. If a target was partially created, inspect it before proceeding.\n")


if __name__ == "__main__":
    main()
