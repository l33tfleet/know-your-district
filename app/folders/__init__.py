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

Deleting is soft. A deleted folder, card or note leaves ordinary reads and frees its limit but
stays recoverable through the `restore_*` calls for `TRASH_KEEP` (30 days); each later delete
purges what has expired, and `purge_deleted` empties the trash early when the size limit bites.
Restores recheck the limits. To remove the feature, turn the flag off and delete the file.

The size limit is a ceiling on the database's pages. A quarter of it is kept for deletes and
purges: other writes stop at three quarters, and the trash keeps its space until purged. A file
already past the ceiling, say after lowering the limit, stays readable but refuses every write.
"""
