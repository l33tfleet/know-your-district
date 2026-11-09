# Security and privacy

**Reads and storage.** Handlers read prebuilt SQLite `data/facts.db`,
`data/snap/facts.db` read-only and local reference files. No accounts, individual
records, chat history, profiles or user content persist.

With `folders` enabled, only `app/folders/store.py` writes: mode 0600, outside
the checkout, at `KYD_FOLDERS_DB` or
`$XDG_STATE_HOME/know-your-district/folders.db` (else `~/.local/state`). Stored: folder name,
district, case IDs, priorities, statuses, timestamps, office-written reasons
(at most 200 characters) and dated notes (at most 1,000 characters).
Keep personal details out of folder names, reasons and notes; notes holding
contact details are always refused. 128-bit link holders can edit. Removal soft-deletes
(`deleted_at`). Cleanup purges folders unwritten for 180 days (startup, daily); a failed pass is logged and retried next day. Folder
answers: no-store, no-referrer, noindex; bodies over 16 KiB: 413. Folders #155 owns future
storage.

**Ask (#183).** The model facade sends TypeSafe one question, chamber/district
and page topic definitions; no figures, folder content, history or client IP.
Individual questions reach TypeSafe before refusal: avoid personal details.
Upstream retention is unverified. Questions, responses, keys and exception
messages are neither stored nor logged by Ask.

`TYPESAFE_API_KEY` stays in the environment, never TOML. Missing keys pause.
The shared runtime reserves input tokens atomically before calls; failures retain
reservations. In-memory IP/token limits require one worker; UTC rollover clears
counters and restarts reset limits. See [settings](agent.md).

Complete serialized input and responses are bounded. No retries; configured
wall-clock timeouts and four transport slots bound waiting/concurrency. Timed-out
transports retain slots until completion. Invalid responses and upstream failures
pause; programming errors expose only type names. Latency stays in memory.

**Requests and logs.** Offline ETL requests Census. Libraries are vendored;
external links leave the app. Access logs may retain addresses, URLs and query
strings; retention is unspecified. Keep secrets and personal details out of URLs.
Only app logs redact folder links. Git exclusions only prevent staging.

Evidence: [handlers](../app/main.py), [facts](../app/facts.py),
[agent](../app/agent/__init__.py), [provider](../app/agent/provider.py),
[ETL](../etl/census.py), [exclusions](../.gitignore), [server](../Makefile),
[folders](../app/folders/store.py), [schema](../app/folders/schema.sql),
[retention](../app/folders/retention.py).
