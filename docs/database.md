# Database migrations and recovery

Run these commands from the repository with the virtual environment activated,
or replace `python` with `.\.venv\Scripts\python.exe` on Windows.

The commands read database credentials from `.env`. They require MySQL 8 and
the `mysql` / `mysqldump` clients. If discovery fails, set `MYSQL_BIN_DIR` in `.env`
to the MySQL `bin` directory. Credentials are passed through a temporary private
client option file, not command-line arguments or backup contents.

## Existing installation: preserve data

1. Stop **all** application workers and other database/upload writers. The
   `--maintenance-confirmed` flag is your acknowledgement; it does not stop them.
   Keep them stopped through backup, baseline, and migration. MySQL's snapshot
   alone cannot make the separate uploads directory consistent.
2. Create a backup with a new filename:

   ```powershell
   python manage_db.py backup --output backups/before-migrations.zip --maintenance-confirmed
   ```

3. Record the baseline and apply pending migrations:

   ```powershell
   python manage_db.py baseline --maintenance-confirmed
   python manage_db.py migrate --maintenance-confirmed
   python manage_db.py status
   ```

4. Restart the app. Keep a protected copy of the backup on another device.

Baseline is for installations created before migration tracking. It checks table
definitions, indexes, foreign keys, checks, triggers, and routines against the
initial schema, then records revision `0001_initial`. It does not recreate tables
or seed over existing data. Comparison ignores column/index order, auto-increment
counters, definers, formatting, and utf8mb4 default collation differences; it is
not a guarantee of identical collation behavior. A mismatch refuses adoption.
Review any mismatch rather than manually stamping an incompatible database.

For later releases, back up, run `migrate --maintenance-confirmed`, then restart.
Do not run baseline again. `status` is read-only.

## New installation

```powershell
python manage_db.py init --database code_share
```

This creates a **new** database and applies versioned migrations. It refuses if
that database already exists. Set `DB_NAME` in `.env` to match. For an existing
empty database, use `migrate --database NAME --maintenance-confirmed`.

The old destructive `schema.sql` has been replaced with an error directing users
to these commands. Do not recover its old reset script to update an installation.

## Backup contents and limits

Each ZIP contains `database.sql`, uploaded files (including profile photos), and
a manifest with SHA-256 hashes, schema definitions, row counts, and file mappings.
It includes triggers, routines, and migration history. `.env` is excluded.
Missing referenced files/photos cause backup to fail rather than claiming a
complete backup. Symlinks/junctions outside storage are rejected.

Backups contain account password hashes and private files. They are ignored by
Git, but are **not encrypted**; store them privately and copy them off-machine.
Archive hashes detect corruption, not malicious replacement. Restore only
backups from a trusted source: SQL backups contain executable database commands.
Database events and server-level accounts/grants are outside this app backup.

A failed backup can leave a `.partial` file. Investigate the error and use a new
output name on retry. Only the final ZIP is a published backup. No automatic
scheduling or retention deletion is configured.

## Restore drill: never overwrite the running installation

Choose a database name and upload directory that do not exist:

```powershell
python manage_db.py restore --backup backups/before-migrations.zip --database code_share_recovery --uploads recovery-uploads
```

Restore checks the archive before creating anything, refuses the configured app
database and any existing database/directory, imports into the new target, checks
schema and row counts, and verifies uploaded bytes. File records are rebased to
the recovery directory. Profile-photo paths remain relative to upload storage.
Existing data and `.env` are not changed. The database account must have create,
DDL, routine, and trigger privileges (including any dump definer requirements).

To inspect the recovered app, stop the normal server, save the original `.env`
settings, and temporarily set `DB_NAME=code_share_recovery` and
`UPLOAD_FOLDER=recovery-uploads`. Start locally, then check login, projects,
private-file permissions, downloads, and profile images. Restore the original
settings to return to the original installation. Cutover is an explicit operator
step, not something the restore command does automatically.

If restore fails after target creation, the partial target is retained for
diagnosis. Use a new target name/directory for retry. Never point the app at it
until verification succeeds. Only remove a failed target after confirming its
exact name/path; the tool never drops an existing database for you.

## Adding migrations

Add the next `migrations/NNNN_description.sql` file. Use unqualified table names;
never include `USE`, database resets, or edits to already applied migration files.
Test on a restored copy first. MySQL DDL implicitly commits: migration execution
is **not** rolled back automatically. The runner records `applying`, then `applied`
or `failed`, checks SHA-256 revisions, and serializes runners with an advisory lock.
Interrupted/failed revisions block further migration attempts. Inspect the state
and recover into a fresh database from the pre-migration backup. Do not blindly
delete migration-history rows or retry partially applied DDL.

## Automated recovery verification

Normal tests avoid the local database:

```powershell
python -m unittest discover -s tests -v
```

The opt-in integration test creates uniquely named disposable MySQL databases,
seeds a project and a binary file, adopts a baseline, backs up, restores, checks
schema/row counts/file bytes, and drops only its own test databases:

```powershell
$env:RUN_MYSQL_ADMIN_TESTS='1'
python -m unittest discover -s tests -p test_database_admin.py -v
Remove-Item Env:RUN_MYSQL_ADMIN_TESTS
```

Use an account allowed to create/drop test databases. This verifies recovery of a
fixture; you should also periodically restore your actual backups and inspect the
recovered app before relying on them in an emergency.
