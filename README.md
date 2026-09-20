# Code Share

Flask application for sharing projects with public or private visibility.

## Local setup

Use Python 3.10 or newer and an existing MySQL database with the application schema.

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

**Do not run `schema.sql` against an existing database: it drops application tables.**
Versioned migrations are still pending.

```powershell
.\.venv\Scripts\python.exe -B -m flask --app app:create_app run --host 127.0.0.1 --port 5000
```

Open http://127.0.0.1:5000. This command starts a development server.

## Security regression checks

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

These tests use temporary files and mocked database calls; they do not change
the local database. Both file routes enforce private-project membership and
serve project uploads as attachments. Only current profile images are inline.

The previously committed database password needs rotation by the database
administrator; removing it from the current code does not erase Git history.
Transaction improvements are pending.
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
