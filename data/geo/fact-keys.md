# Fact geography join

Database: data/facts.db

PASS: exact House and Senate fact-key equality; missing=[]; extra=[]; sha256=5c38791529a03f15cfd14fe9bb1c57c9c2f1360ad0b6326c9ed69779221ff3da

Method: SELECT DISTINCT geography FROM facts, read-only; exclude state:15 and county keys, translate district IDs to WO59 qualified keys, compare both directions. Key equality does not prove fact completeness or geographic correspondence.
