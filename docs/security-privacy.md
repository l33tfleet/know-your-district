# Security and privacy

This note describes repository mechanisms; hosting configuration is separate.

**Data and individuals.** The app serves district brief pages, a picker and a
health response. Handlers open committed SQLite fact databases under `data/`
read-only (`mode=ro`); ETL builds them from public, aggregate Census ACS
tables; district shapes are State boundary layers ([`data/geo/`](../data/geo/)). App handlers neither collect nor persist personal information,
chat history or user profiles. There is no person lookup or inference about
individuals. The product's aggregate-only rule permits published population
tables, never individual records ([data and licences](data.md#data-licences)).

**Folder store (not yet built).** District folders will be the one writable
store: the SQLite file `KYD_FOLDERS_DB`, outside the checkout, written only
through `app/folders/store.py` while the `folders` flag is on. It holds folders
of districts, never data about individuals, and deletes a folder idle for 180
days. A folder link is a secret: anyone holding it can open the folder.

**Model provider.** No chat endpoint or external model client is implemented.
No prompts, conversation history, district facts or credentials are sent to a
model provider by this app.

**Limits and costs.** No rate limiter, token budget or cost cap is implemented,
and no model calls incur provider charges.

**Secrets.** The app reads no model API key. ETL accepts an optional Census API
key, sent to Census in request parameters; HTTP errors suppress keyed URLs.
Git ignore patterns cover
`.env`, `.env.*` (except `.env.example`), private-key files and `secrets/`;
they prevent accidental staging, not exposure of tracked files.

**Request logs.** `make run` uses Uvicorn's default access logging, which includes
client addresses and request URLs, including query strings. Do not put personal
information or secrets in URLs. The repository defines no log-retention policy;
hosting and proxy logging settings are outside this note.

Evidence: [handlers](../app/main.py), [fact reads](../app/facts.py),
[agent](../app/agent/__init__.py), [ETL](../etl/census.py),
[secret exclusions](../.gitignore), [server command](../Makefile).
