# Code Share

Flask application for sharing projects with public or private visibility.

## Local setup

Use Python 3.11 or newer and MySQL 8 with the application schema.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated value in `SECRET_KEY` in `.env`, and configure your database
credentials. Do not overwrite an existing `.env`. The app refuses startup without
a secret of at least 32 characters and a database password. Keep `.env` private.
Changing the secret signs out existing sessions. Enable `SESSION_COOKIE_SECURE`
when deploying with HTTPS; leave it false for local HTTP.

Use `python manage_db.py init --database code_share` for a new database.
For existing data, follow the [backup and baseline instructions](docs/database.md)
before applying migrations. The old destructive `schema.sql` is now disabled.

```powershell
.\.venv\Scripts\python.exe -B -m flask --app app:create_app run --host 127.0.0.1 --port 5000
```

Open http://127.0.0.1:5000. This command starts a development server.

## Security regression checks

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

These tests use temporary files, mocked calls, and an in-memory SQLite test adapter; they do not change
the local database. Both file routes enforce private-project membership and
serve project uploads as attachments. Only current profile images are inline.

The previously committed database password needs rotation by the database
administrator; removing it from the current code does not erase Git history.
The ignore rules prevent new uploads and caches being added; previously tracked
files remain in Git until a separate cleanup.

## Form protection and login limits

Every POST form includes a session-bound CSRF token, including login, signup,
uploads, and logout. Missing, invalid, or expired tokens return HTTP 400 before
an action runs. Logout is POST-only. Successful login/signup clears the old
session so its CSRF token cannot be reused.

Login accepts at most 5 POST attempts per minute and 30 per hour per client IP,
including successful attempts. Excess attempts return HTTP 429 with Retry-After.
GET requests are not limited. Set LOGIN_RATE_LIMIT to adjust these limits.
Forwarded IP headers are not trusted by default; configure trusted proxy handling
for your deployment before running behind a reverse proxy.

RATELIMIT_STORAGE_URI defaults to memory:// for local single-process development.
These counters reset on restart and are not shared across workers. Production
must use shared storage, for example redis://localhost:6379/0 (install the Redis
extra with pip install "Flask-Limiter[redis]==4.1.1").

## Project transactions and file recovery

Project POST actions commit their database changes and activity records together.
Failures roll back the operation instead of retaining partial language lists,
project metadata, or activity records. Project-ID mutations acquire a row lock
to serialize uploads with project deletion. This is not a migration: the
existing InnoDB tables and cascading foreign keys are still required.

Uploads use exclusive file creation, so duplicate names do not overwrite other
uploads. Empty files and partial writes are cleaned up. A database statement
failure removes the newly saved upload after rollback. If the connection fails
during commit, the outcome may be uncertain: bytes are retained and the failure
is logged, so a possibly committed file record does not lose its contents.

File and project deletion remove database records before deleting registered
files from storage. A SQL or commit failure leaves the stored files intact.
Disk cleanup failures are logged and shown as warnings; deleted records cannot
be downloaded through the application. Unregistered files and empty directories
are not recursively deleted.

There is no atomic transaction spanning MySQL and disk. A process crash or disk
cleanup failure can leave orphaned bytes. Administrators should reconcile stored
paths against `files.filepath` and `users.profile_image` before manually removing
any orphan. Cleanup is not automatically retried. Profile-photo replacement and
follow/unfollow changes now use transactions as well (see below).

## Browsing project files

Open a project and choose **Browse files**, or **Preview** beside an upload.
Text and code files have escaped, syntax-highlighted previews with line numbers.
Markdown READMEs render automatically when present. README HTML is sanitized;
scripts, embedded HTML widgets, and remote images are not rendered.

ZIP uploads can be browsed by folder without extracting them to disk. Private
projects keep their membership checks on every preview request. Previews are
limited to 1 MB of UTF-8 text, 5,000 ZIP entries, and a bounded compression ratio.
Unsupported, encrypted, oversized, or unsafe files show a download alternative.
ZIP downloads contain the original archive, not just the selected member.

## Profile photos and storage cleanup

Photo replacement/removal commits the database update before removing the old
photo. Failed database writes remove the new photo; uncertain commits preserve
both for reconciliation. Images are decoded and re-encoded as static PNGs,
limited to 10 MB and 20 million input pixels, and resized to at most 1024×1024.
Animations and embedded metadata are not retained.

Scan unreferenced uploads without changing files:

```powershell
python manage_db.py orphans
```

After stopping all writers and making a backup, move them to a NEW quarantine
directory (the command never permanently deletes them):

```powershell
python manage_db.py orphans --quarantine backups/orphans-review --maintenance-confirmed
```

Both project files and current profile photos are protected. Missing references
block quarantine so potential recovery copies stay available. The quarantine
manifest records the original upload root, relative paths, and SHA-256 hashes;
restore a quarantined file by copying it from `files/<relative-path>` back to its
original location after verifying the hash and confirming the target is absent.
If a move fails partway, completed moves and remaining originals are preserved;
the manifest describes the complete planned set. Do not delete quarantines until
you have reviewed them. The current repository still tracks historical uploads;
quarantining those files produces Git deletions that must be reviewed separately.

## GitHub checks

`.github/workflows/tests.yml` runs unit/security tests on Python 3.11 and 3.12
for pushes and pull requests. A separate MySQL 8 job exercises fresh migrations,
baseline adoption, backup/restore, and failure recovery on disposable databases.
The workflow uses only temporary CI credentials and does not need your `.env`.
It will first run on GitHub after the commit is pushed.
