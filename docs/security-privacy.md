# Security and privacy

This note describes the repository's current scaffold, not a deployed server's
configuration.

**Data and individuals.** The app serves a placeholder home page, static files
and a health response. It loads no Census or State dataset and opens no
database. App handlers neither collect nor persist personal information,
chat history or user profiles. There is no person lookup or inference about
individuals. The product's aggregate-only rule permits published population
tables, never individual records; the specified source is public Census ACS
aggregate estimates ([data and licences](data.md#data-licences)).

**Model provider.** No chat endpoint or external model client is implemented.
No prompts, conversation history, district facts or credentials are sent to a
model provider by this app.

**Limits and costs.** No application rate limiter, token budget or monetary cost
cap is implemented. There are no model calls generating provider charges.
This is not protection against web traffic or hosting costs.

**Secrets.** The app currently reads no model API key. Git ignore patterns cover
`.env`, `.env.*` (except `.env.example`), private-key files and `secrets/`.
These patterns prevent ordinary accidental staging; they neither encrypt
secrets nor protect files already tracked by Git.

**Request logs.** `make run` uses Uvicorn's default access logging, which includes
client addresses and request URLs, including query strings. Do not put personal
information or secrets in URLs. The repository defines no log-retention policy;
hosting and proxy logging settings are outside this note.

Evidence: [handlers](../app/main.py), [template](../templates/home.html),
[agent](../app/agent/__init__.py), [ETL](../etl/__init__.py),
[secret exclusions](../.gitignore), [server command](../Makefile).
