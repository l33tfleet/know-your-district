"""District folders: the one writable store, the SQLite file named by `KYD_FOLDERS_DB`.

`store.py` is the only module that touches that file, which stays outside the checkout with mode
0600. The schema keeps keys and office state, never figures. Nothing here serves a route yet, and
nothing writes unless the `folders` flag is on. To remove the feature, turn the flag off and
delete the file. A pending migration is refused if the size limit cannot hold the file.
"""
