# AGENTS.md

Read this file in full before changing anything. It holds the product rules, the
stack pins, the layout and the test rules for every work order. `CLAUDE.md`
points here; the reviewer rubric in `.factory/review.md` checks the same rules
line by line, and `docs/data.md` holds the data facts (indicators, vintage,
reliability thresholds, known traps). If these files ever disagree, stop and
say so in the PR instead of guessing.

## What this is

Know Your District is a public web tool for Hawaiʻi legislators and their staff.
Pick a State House or Senate district and get a one-page, printable, cited brief
of who lives there, how sure the numbers are, and which public programs may
help. A chat bar edits the brief. Figures come only from published tables, U.S.
Census ACS 5-year first. The live site is `https://district.hawaiitechmentors.org`.

## Product rules

These are not style preferences. A PR that breaks one is not done.

1. **Cited.** Every number shown or spoken cites its source, table ID, vintage,
   geography and method.
2. **Uncertain, in words.** Uncertainty is shown in words next to the figure:
   the margin of error, and a reliability flag from the coefficient of variation
   (thresholds in `docs/data.md`).
3. **No model-written numbers.** No number is written by a language model.
   Numbers come only from tool results that read the fact table.
4. **Populations, never individuals.** No lookups of, or inferences about, a person.
5. **Nonpartisan.** No opinions on candidates, parties, votes or bills.
6. **Hawaiian spelling.** Hawaiian place names use the ʻokina (ʻ, U+02BB, not an
   apostrophe or a left quote) and the kahakō (ā ē ī ō ū) correctly:
   Hawaiʻi, Kauaʻi, Lānaʻi, Molokaʻi, Oʻahu, Kahoʻolawe, Niʻihau.
7. **Never "you qualify".** Never tell anyone they qualify for a program.
   Programs "may help"; the agency decides eligibility; point to the official
   program page and to 211 (Aloha United Way 211).

## Stack (decided)

| Piece | Pin | Notes |
|---|---|---|
| Language | Python 3.12+ | `.python-version` says 3.12 |
| Packaging | `uv` | `uv sync` installs from `uv.lock`; add deps with `uv add`, never by hand-editing the lock |
| Web | FastAPI with Jinja2 templates | ASGI app served as `uvicorn app.main:app` |
| Interactivity | htmx 2.0.x, vendored at `static/vendor/htmx-2.0.11.min.js` | see the htmx warning below |
| Map (later) | Leaflet 1.9.x with the SVG renderer | vendored under `static/vendor/` when the map lands |
| Data | SQLite, read-only at runtime, built ahead of time by `etl/` | open with `mode=ro`; the app never writes |
| Models | Pydantic | every figure is a Pydantic model carrying its citation and uncertainty |
| Checks | ruff, pyright (strict), import-linter, pytest | all run by `make check` |

**htmx: use 2.0.x syntax only.** htmx 4 exists and its docs are now the default
online. Its attributes, events and extension APIs differ from 2.0. Do not copy
htmx 4 examples, do not mix the two syntaxes, and do not upgrade the vendored
file. Before using a doc page or example, check that it is for htmx 2.x.

**SQLite: never hold a transaction open across a model call.** Read what you
need, close the cursor, then call the model.

**No CDNs.** Front-end libraries are vendored under `static/vendor/` with the
version in the file name.

## Layout

| Path | What goes there |
|---|---|
| `app/` | app core: ASGI entry point (`app/main.py`), config, shared models |
| `app/sections/` | page sections of the brief, one module each; a section may import app core, never another section (import-linter enforces this) |
| `app/analysis/` | pure functions over figures (reliability flags, comparisons) |
| `app/tools/` | tools the chat agent calls; the only path from the fact table to a spoken number |
| `app/agent/` | the chat agent: prompts, tool wiring, guard rails |
| `app/web/` | routes, htmx partials, request/response glue |
| `etl/` | builds the read-only SQLite fact table from published tables |
| `data/` | the built database and small reference files (caches are git-ignored) |
| `templates/` | Jinja2 templates |
| `static/` | CSS, images, vendored JS |
| `scripts/` | operator scripts (`scripts/smoke.py`, …) |
| `docs/` | `docs/data.md` and other reference docs |
| `tests/regressions/` | new tests from every work order (append-only, see below) |
| `tests/golden/` | golden files (expected rendered output) |
| `tests/evals/` | eval cases for the agent and the data traps; run by `make evals` |

## Commands

```
uv sync                                   # install pinned dependencies
make check                                # ruff, pyright strict, import-linter, pytest, evals
make run                                  # serve on http://127.0.0.1:8000
make smoke BASE_URL=http://127.0.0.1:8000 # GET /healthz must return 200
make format                               # ruff fixes and formatting
```

`make check` passing is part of done, every time.

## Tests: where they go

- Any new test goes in a **new file under `tests/regressions/`**. Name it after
  the work order, e.g. `tests/regressions/test_wo12_poverty_brackets.py`.
- `tests/regressions/` is **append-only**: never edit, rename or delete an
  existing file there. The `regressions-append-only` CI job diffs the PR against
  its merge base and fails otherwise.
- A regression test pins a fixed bug or a decision a work order states, not an
  incidental design detail.
- The one exception is a spec change. If a work order changes the spec that an
  existing regression test pins, the work order's Issue carries a line
  `Supersedes: tests/regressions/<file>.py::<test>`. The PR (branch
  `agent/<issue>-…`) may then delete that one top-level test from its file and
  change nothing else in that file (checked at the AST level); the replacement,
  at least as strict, goes in a new file. The commit message carries the same
  `Supersedes:` line with the work order's words that require it.
- Leave the rest of `tests/` alone unless the work order says otherwise. It
  belongs to the Code Owner (characterization tests of the rendered pages live
  in `tests/test_pages.py`), and touching it holds the PR for review.
- Data traps listed in `docs/data.md` each become an eval case in `tests/evals/`.

## Mechanical guard rails

- pyright runs in strict mode over `app/`, `etl/`, `scripts/`, `tests/` and `.github/scripts/`.
- ruff PGH003 and PGH004 make a blanket `# type: ignore` or bare `# noqa` fail.
  Fix the type or name the exact rule (`# noqa: E501`, `# pyright: ignore[reportXxx]`),
  with a comment saying why.
- import-linter: page sections are independent of each other.
- `.github/CODEOWNERS` gives `@k7lim` the guard-rail files (`pyproject.toml`,
  `Makefile`, `.github/`, `AGENTS.md`, `CLAUDE.md`, `.factory/`, `conftest.py`,
  `/fixtures/`, `/scripts/independent_*`). A PR that touches them waits for
  that review instead of auto-merging. `tests/regressions/` is unowned on purpose.

## Scope test

If a change won't make a judge say "wow" in a four-minute demo, it's out. The
exception is foundational work (it deploys, it stays up, every figure is
sourced), because the wow rests on it. Touch only the files your work order allows.
