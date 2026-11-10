# Suggestion decisions

Schema v2 ([`suggestions.sql`](../app/folders/suggestions.sql), step 1 of #154) keeps, per
folder and match key, the source, date, decision and timestamps; an accepted match's card is
its next step. Rows go with their folder (rotation moves them, retention purges them).
[`store.py`](../app/folders/store.py)'s `decide` is one transaction and keeps the card on later
decisions; `list_decisions` returns detached [references](../app/suggestions.py).

**Rollback.** A failed migration leaves v1 and every record unchanged. Revert: stop decision writes,
run `DROP TABLE suggestions; PRAGMA user_version = 1;` in one transaction, deploy the old app.
