# Security and privacy

**Reads.** Handlers read prebuilt SQLite `data/facts.db`, `data/snap/facts.db`
read-only and local reference files. No accounts, profiles, chat history or
individual records persist; folders are the only user content kept.

**Folders.** Only `app/folders/store.py` writes, with `folders` on: mode 0600,
outside the checkout, at `KYD_FOLDERS_DB` or
`$XDG_STATE_HOME/know-your-district/folders.db` (else `~/.local/state`).
Whoever holds a folder's 128-bit link owns it: they can view and edit it. Stored: folder name, district, case IDs, [decisions](suggestions.md),
priorities, statuses, timestamps, office-written reasons (at most 200
characters) and dated notes (at most 1,000 characters). Keep personal details
out of folder names, reasons and notes; notes holding contact details are always
refused, as are phone numbers, emails and addresses in any field. Removal
soft-deletes (`deleted_at`). Cleanup purges folders unwritten for 180 days
(startup, daily); failed passes are logged, retried. Folder answers: no-store,
no-referrer, noindex; bodies over 16 KiB: 413.

**Demo (#155).** The [demo folder](demo-folder.md) is an immutable seed, refreshed
nightly. A visitor's first edit makes a private copy with a new link; refreshes
never touch copies.

**Ask (#183).** The model facade sends TypeSafe one question, district and topic
definitions; no figures, folders, history or client IP. Questions reach TypeSafe
before refusal: avoid personal details. Upstream retention is unverified. Ask
stores and logs no questions, responses, keys or exception messages.
`TYPESAFE_API_KEY` stays in the environment. Inputs, responses, waiting and
concurrency are bounded; no retries. Limits, timeouts and token
reservations are in [settings](agent.md).

**Requests and logs.** Offline ETL requests Census. Libraries are vendored;
external links leave the app. Access logs may retain addresses, URLs and query
strings; retention is unspecified. Keep secrets and personal details out of
URLs. Only app logs redact folder links. Git exclusions only prevent staging.

Evidence: [handlers](../app/main.py), [facts](../app/facts.py),
[agent](../app/agent/__init__.py), [provider](../app/agent/provider.py),
[ETL](../etl/census.py), [exclusions](../.gitignore), [server](../Makefile),
[folders](../app/folders/store.py), [schema](../app/folders/schema.sql) [v2](../app/folders/suggestions.sql),
[retention](../app/folders/retention.py), [demo](../app/folders/demo.py),
[timer](../deploy/systemd/kyd-demo-reset.timer).
