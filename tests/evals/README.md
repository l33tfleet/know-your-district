# Evals

Eval cases for the chat agent and the data traps in `docs/data.md`, one
pytest file per behavior (`test_*.py`). `make evals` (part of `make check`)
runs them; an empty suite passes.

An eval checks behavior end to end: given a district and a question, the brief
or the chat reply must cite its figures, show uncertainty in words, take every
number from a tool result, and follow the product rules in `AGENTS.md`.
Evals must run offline and deterministically in CI (recorded model responses
or a stub model), so `make check` never needs a network or an API key.

Readability collection (WO141 step 2 / #186) is exercised by
`tests/regressions/test_wo141_collection.py`. Run the offline collector with:

```sh
uv run python -m scripts.readability_corpus > /tmp/readability-corpus.json
uv run python -m scripts.readability_corpus --recordings /path/to/answers.jsonl > /tmp/readability-corpus.json
```

The JSON contains separate blocks and their scores, never a whole-page average.
It walks every scalar YAML leaf under `app/` and `data/`, including catalog
metadata, labels, list entries, empty and null values. IDs retain file and
key/index paths. It renders home, not-found, both picker partials and every
House and Senate brief, covering all counties. Explicitly labelled synthetic
fixtures exercise missing figures and the multi-county branch (the committed
overlay currently has only single-county districts). These fixtures are eval
inputs, not published district facts. HTML blocks retain inline prose, labels,
SVG text and accessible text attributes; scripts and styles are excluded.
Only marked citation metadata values (`source`, `table_id`, `vintage`,
`geography`, `endpoint` on `dd`/`code`) receive exclusion spans. Citation
containers, summaries, field labels, methods, uncertainty and adjacent caveats
remain scored. YAML leaves receive no citation exclusions.

Recorded JSONL follows `docs/plain-language.md`, with `kind` extended to accept
`"refusal"` as well as `"answer"`. Each record requires a nonblank unique `id`,
original `text`, and `citation_spans` as two-integer character-offset pairs.
Invalid records, duplicate IDs and invalid spans fail explicitly; text is never
rewritten before scoring. Record only citation metadata spans, never surrounding
explanations. No model call, API key or invented answer is used. No recordings
are supplied by this work order: `absent` reports missing answer and refusal
coverage independently. Missing or wholly unscorable YAML sources, rendered
pages and recording kinds are also reported there; empty/unscorable individual
leaves remain in the corpus with `grade: null`, never a passing zero. This step
collects evidence; it adds no readability threshold or gate.
