-- The destructive reset script has been retired.
-- New databases: python manage_db.py init --database code_share
-- Existing databases: see docs/database.md for backup and baseline steps.
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Use manage_db.py; see docs/database.md';
