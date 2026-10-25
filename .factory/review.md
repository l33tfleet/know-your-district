# Reviewer rubric

The review engine reads this file from `main`. Check every line against the
diff. Each line is pass/fail; cite `file:line` for any failure. The rules come
from `AGENTS.md`; data facts from `docs/data.md`.

## Product rules (one line each)

- [ ] **R1 Cited:** every number the change shows or speaks carries source, table ID, vintage, geography and method, rendered next to the figure.
- [ ] **R2 Uncertainty:** every figure shows its margin of error and a reliability flag in words (CV thresholds from `docs/data.md`: ≤ 15% reliable, 15–30% moderate, > 30% use with caution); caution is displayed, not hidden.
- [ ] **R3 No model numbers:** no number reaches the page or the chat from a language model's text; every number comes from a tool result that read the fact table.
- [ ] **R4 Populations, never individuals:** no feature looks up, stores or infers anything about a named or identifiable person.
- [ ] **R5 Nonpartisan:** no text gives opinions on candidates, parties, votes or bills.
- [ ] **R6 Hawaiian spelling:** Hawaiian place names use the ʻokina (ʻ, U+02BB, not `'` or `‘`) and kahakō (ā ē ī ō ū) correctly.
- [ ] **R7 Never "you qualify":** program text says programs "may help", says the agency decides eligibility, and links the official program page and 211.

## Ground rules

- [ ] **G1 Tests placed right:** new tests are in new files under `tests/regressions/`; no existing file there is edited, renamed or deleted unless the Issue's `Supersedes:` line names that exact test, and the replacement is at least as strict.
- [ ] **G2 Regression tests pin decisions:** each regression test pins a fixed bug or a decision the work order states, not an incidental design detail.
- [ ] **G3 Scope:** the diff touches only files the work order allows, and nothing outside its Scope "In" list.
- [ ] **G4 Guard rails intact:** no blanket `# type: ignore` or bare `# noqa`; no loosening of pyright strict, ruff rules or the import-linter contract; no section module imports another section.
- [ ] **G5 Stack pins:** htmx 2.0.x syntax only (no htmx 4 attributes or APIs); Leaflet 1.9.x with the SVG renderer; no CDN scripts; SQLite opened read-only; no transaction held open across a model call; figures are Pydantic models.
- [ ] **G6 Data traps:** poverty multiples use the nearest named C17002 bracket, never interpolated, and are called a lower bound; benefit counts note the survey undercount; DP/S variable labels are asserted for the pinned vintage.
- [ ] **G7 Done:** `make check` passes.
