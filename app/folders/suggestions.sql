-- Version 2 of the folder store (docs/suggestions.md): adds a table; v1 stays as it was.
-- One decision per folder and suggested match; an accepted one's card is its next step.
CREATE TABLE suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id TEXT NOT NULL REFERENCES folders (id) ON DELETE CASCADE,
    suggestion_key TEXT NOT NULL,
    chamber TEXT NOT NULL CHECK (chamber IN ('house', 'senate')),
    district INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('district_matches')),
    dated TEXT NOT NULL CHECK (dated GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'dismissed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
CREATE UNIQUE INDEX suggestions_live ON suggestions (folder_id, suggestion_key, chamber, district);
