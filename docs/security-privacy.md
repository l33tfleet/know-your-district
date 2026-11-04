# Security and privacy

**Reads and storage.** Handlers read prebuilt SQLite `data/facts.db` and
`data/snap/facts.db` read-only and local reference files. No accounts, individual
records or person inferences exist.

With `folders` enabled (preview today), only `app/folders/store.py` writes:
mode 0600, outside the checkout, at `KYD_FOLDERS_DB` or
`$XDG_STATE_HOME/know-your-district/folders.db` (else `~/.local/state`). Stored:
folder name, district, case IDs, priority, status, timestamps and office-written
reason (at most 200 characters). No figures or data about individuals; keep
personal details out of reasons. Anyone possessing the 128-bit link can edit.
Removal soft-deletes (`deleted_at`); no automatic purge or retention period exists. No other
user content, chat history or profiles persist.

**Ask guards.** The runtime reads `TYPESAFE_API_KEY` from the process environment
(systemd `EnvironmentFile` outside the repo), never TOML. Missing keys pause
without provider calls. Timeouts and facade-declared upstream failures pause;
other errors fail with only their type name, suppressing messages and chains.
In-memory trusted-IP counters allow 10/minute and 100/UTC day. Atomic global
daily input-token reservations precede calls; failures retain reservations.
One shared runtime, one worker only: replicas multiply limits; restarts reset
them. IP counters clear at UTC rollover/process exit. See [settings and
limitations](agent.md), including subsequent input-bound enforcement.

**Requests and logs.** No live model-provider HTTP or chat endpoint is wired
yet (#183/#184). Offline ETL requests Census; keyed errors suppress URLs.
Libraries are vendored; external links leave the app. Access logs may retain
addresses, URLs and query strings; no log-retention policy exists. Keep secrets
and personal details out of URLs; folder links grant access to log readers.
Git exclusions prevent accidental staging only. Folders #155 owns future storage.

Evidence: [handlers](../app/main.py), [facts](../app/facts.py),
[agent](../app/agent/__init__.py), [runtime](../app/agent/runtime.py),
[ETL](../etl/census.py), [exclusions](../.gitignore), [server](../Makefile),
[folder store](../app/folders/store.py), [schema](../app/folders/schema.sql).
