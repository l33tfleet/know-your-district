"""District folders: the one writable store, the SQLite file named by `KYD_FOLDERS_DB`.

`store.py` is the only module that touches that file. `models.py` validates what goes in.
Folders keep keys and office state, never figures: pages re-read every number from the fact
table. Nothing here serves a route yet, and nothing writes unless the `folders` flag is on.

Backup and restore. The file must stay outside the checkout with mode 0600, and so must every
copy of it. The live database is in WAL mode, so never copy the file alone. To back up, with
the app running or not:

    umask 077 && sqlite3 "$KYD_FOLDERS_DB" ".backup '/secure/path/folders-backup.db'"

To restore, stop the app, then remove any `-wal` and `-shm` files beside the live file, copy
the backup over it, and run `chmod 600 "$KYD_FOLDERS_DB"`. The next open refuses a file with
any other mode, and applies any migrations the backup is missing.
"""
