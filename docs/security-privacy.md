# Security and privacy

This note describes today's app; hosting configuration is separate.

**Reads and storage.** Handlers read prebuilt SQLite databases `data/facts.db`
and `data/snap/facts.db` (read-only, `mode=ro`, from public, aggregate Census
ACS tables) and local reference files. There are no accounts, individual
records, person lookups or inferences about individuals. See
[data and licences](data.md#data-licences).

When the `folders` flag is on (`?preview=1` only today), the app writes one
SQLite file outside the checkout, only through `app/folders/store.py`, mode
0600: `$XDG_STATE_HOME/know-your-district/folders.db` (else under
`~/.local/state`), or `KYD_FOLDERS_DB` if set. It holds folder name, district,
saved case ids, priority, status, timestamps and a reason of at most 200
characters typed by the office. It holds no figures and no data about
individuals; offices must also keep personal details out of reasons. Anyone with
the 128-bit link can open and edit the folder. Removal is a soft delete
(`deleted_at`), offered on no page yet; no automatic purge or retention period
is defined. The app persists no other user content, chat history or profiles.

**Third-party requests.** The app makes no runtime Census or model-provider
requests, has no chat endpoint and reads no model API key. Front-end libraries
are vendored. External links leave the app. Offline ETL requests Census data,
with an optional API key; HTTP errors suppress keyed URLs.

**Logs and secrets.** Access logs (Uvicorn's default, hosting, proxy) may keep
client addresses and request URLs, including query strings; no log-retention
policy exists. Keep personal information and secrets out of URLs, except folder
links, which log readers can open. Git ignore patterns guard
environment files, private keys and `secrets/` against accidental staging only.

**Planned changes.** Ask (#183) owns updates to this note when it lands,
including provider disclosures. Folders (#155) own later storage changes.

Evidence: [handlers](../app/main.py), [fact reads](../app/facts.py),
[SNAP reads](../app/snap.py), [agent](../app/agent/__init__.py),
[ETL](../etl/census.py), [secret exclusions](../.gitignore),
[server command](../Makefile), [folder store](../app/folders/store.py),
[folder schema](../app/folders/schema.sql).
