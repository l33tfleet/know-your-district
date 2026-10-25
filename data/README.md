# Data

The read-only SQLite fact table that the app reads at runtime, built ahead of
time by `etl/` from published tables (see `docs/data.md`), plus small reference
files. Raw downloads go in `data/cache/` or `data/raw/`, which are git-ignored.

The app opens the database read-only (`mode=ro`) and never writes to it.
