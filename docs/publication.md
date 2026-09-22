# Preparing the repository for public sharing

The publication cleanup removes uploaded documents/photos, Python bytecode,
private environment files, and local recovery notes from reachable Git history.
Historical hardcoded credential values are redacted. The exposed local database
credential was rotated and the application's private `.env` updated separately.
Each installation must supply its own secrets.

The private rollback bundle under `backups/` retains the original history for
local recovery. **Never publish that bundle**, private backups, `.env`, or uploads.
The ignore rules protect them from ordinary `git add` commands, not `git add -f`.

Local history cleanup does not erase copies already on GitHub, in forks, or in
other clones. Rewritten commits have different IDs. Updating an existing remote
requires a coordinated force push after checking for others' newer changes.
Collaborators should re-clone afterward so they do not reintroduce old commits.
Alternatively, publish the cleaned repository to a new, empty remote.

For an already public repository, old pull-request references or cached commit
pages can retain removed content. Follow GitHub's sensitive-data removal process
where applicable; a normal push or local rewrite alone cannot remove every copy.
Credential rotation is necessary even when the visible history is clean.

Before publishing, confirm that automated tests pass, review the included static
assets for ownership/licensing, and follow your institution's AI-disclosure rules.
No license for third-party assets is implied by this cleanup.
