# Security and privacy

This note describes today's app; hosting configuration is separate.

**Reads and storage.** Handlers read prebuilt SQLite databases
`data/facts.db` and `data/snap/facts.db` with `mode=ro` (read-only), plus local
reference files for district/county mappings, program descriptions, referrals
and configuration. ETL builds the databases from public, aggregate Census ACS
tables. There are no accounts, individual records, person lookups or inferences
about individuals. The app persists no user content, chat history or profiles;
it has no writable user store today. See [data and licences](data.md#data-licences).

**Third-party requests.** Brief requests read local files; no runtime Census
or model-provider requests are made. No chat endpoint or external model client
is implemented, and the app reads no model API key. Front-end libraries are
vendored locally, without CDNs. Following external links to agencies or 211
sends the browser to those services, whose privacy practices apply.
Offline ETL requests Census data and accepts an optional Census API key in
request parameters; HTTP errors suppress keyed URLs.

**Logs and secrets.** Uvicorn's default access logging includes client addresses
and request URLs, including query strings. Do not put personal information or
secrets in URLs. Hosting and proxy access logs may also retain request data;
the repository defines no log-retention policy. Git ignore patterns cover
environment files, private keys and `secrets/`; they prevent accidental staging,
not exposure of tracked files.

**Planned changes.** Ask (#183) and folders (#155) own updates to this note when
they land, including provider disclosures and any storage/retention behavior.
Neither capability is available today.

Evidence: [handlers](../app/main.py), [fact reads](../app/facts.py),
[SNAP reads](../app/snap.py), [agent](../app/agent/__init__.py),
[ETL](../etl/census.py), [secret exclusions](../.gitignore),
[server command](../Makefile).
