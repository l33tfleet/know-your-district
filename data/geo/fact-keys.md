# Fact geography join

Database: data/facts.sqlite

Join unavailable or failed; #24 must deliver the real fact database: unable to open database file

Method: SELECT DISTINCT geography FROM facts, read-only; exclude state:15 and county keys, translate district IDs to WO59 qualified keys, compare both directions. Key equality does not prove fact completeness or geographic correspondence.
