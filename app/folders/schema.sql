-- Version 1 of the folder store. Applied by app/folders/store.py inside one transaction.
-- Keys and office state only: no figures, and no column for anything about a person.
-- A set deleted_at is the trash: ordinary reads skip the row until restore or purge.
-- A card's status runs idea, contacted, planned, done.

CREATE TABLE folders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
) STRICT;

CREATE TABLE cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id TEXT NOT NULL REFERENCES folders (id) ON DELETE CASCADE,
    card_key TEXT NOT NULL,
    chamber TEXT NOT NULL CHECK (chamber IN ('house', 'senate')),
    district INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('idea', 'contacted', 'planned', 'done')),
    priority TEXT NOT NULL CHECK (priority IN ('high', 'normal', 'low')),
    reason TEXT CHECK (length(reason) <= 200),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
) STRICT;

CREATE UNIQUE INDEX cards_live ON cards (folder_id, card_key, chamber, district)
    WHERE deleted_at IS NULL;
CREATE INDEX cards_by_folder ON cards (folder_id);

CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
    dated TEXT NOT NULL,
    body TEXT NOT NULL,
    confirmed INTEGER NOT NULL CHECK (confirmed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
) STRICT;

CREATE INDEX notes_by_card ON notes (card_id);

CREATE TABLE rate_buckets (
    scope TEXT PRIMARY KEY,
    window_start INTEGER NOT NULL,
    hits INTEGER NOT NULL
) STRICT;
