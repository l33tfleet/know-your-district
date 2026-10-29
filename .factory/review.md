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
- [ ] **G5 Stack pins:** htmx 2.0.x syntax only (no htmx 4 attributes or APIs); Leaflet 1.9.x with the SVG renderer; no CDN scripts; SQLite opened read-only, with one exception: the folder store `KYD_FOLDERS_DB` may be written, but only from `app/folders/store.py`, only while the `folders` feature flag is on, only to a file outside the checkout, and never with data about individuals (R4); any other write, or a write to that file from any other module, fails; no transaction held open across a model call; figures are Pydantic models.
- [ ] **G6 Data traps:** poverty multiples use the nearest named C17002 bracket, never interpolated, and are called a lower bound; benefit counts note the survey undercount; DP/S variable labels are asserted for the pinned vintage.
- [ ] **G7 Done:** `make check` passes.
- [ ] **G8 Claim ladder:** a change to data, programs, matches, chat claims or maps labels each claim with the strongest level its evidence supports (relevant need, modeled eligibility, comparable nonparticipation) and meets the matching row of "Acceptance evidence for reviewers" in `docs/agent-docs/district-data-build-guide.md`; no eligible-nonparticipant count, unclaimed-dollar total or uptake gap appears without that guide's comparability gate.
- Every validation or failure branch the change adds or touches has its own negative test, and each test triggers exactly one check (input that only that check rejects, asserting its specific error), so no branch goes untested and no test passes because a different check fired.
- Any prose the change adds or leaves in place that describes the current state of the repo or the run (docs preambles, README claims, commit messages about test or check results) matches the merged code and the supplied `make check` output; stale or contradicted statements fail.

## Engineering (docs/engineering.md)

- [ ] **E4 Facade externals:** wrap upstream APIs and platform bindings behind a facade that hides their shapes, measures call latency and contains upstream surprises.
- [ ] **E6 Flat modules:** use few files per domain, no inheritance or shared base classes, small interfaces hiding real complexity, sibling comments on copies and shared-pattern extraction after three domains.
- [ ] **E7 Validate edges, trust core:** validate enums and untrusted strings at boundaries, reject unknown options loudly with valid choices and avoid re-validation inside the core.
- [ ] **E8 Privacy in schema:** put visibility, consent and hide-flags in the data model so new views cannot bypass privacy.
- [ ] **E12 Secrets never in source:** keep credentials in environment variables or a secret store with rotation independent of code changes or redeployment, and document CLI environment variables and required skill auth without secrets.
- [ ] **E13 Characterize before you change:** write characterization tests capturing actual behavior before modifying external dependencies, upstream code or an unfamiliar codebase.
- [ ] **E16 Input hardening:** treat agent and user inputs as untrusted, canonicalize and sandbox paths, reject control characters, reject `?` and `#` in identifiers and reject `%` in resource names at CLI/API boundaries.
- [ ] **E17 Safety rails:** provide validated previews for mutating commands, explicit destructive intent, actions modeled as data with one executor, plan review before multi-step or production changes, shared-state soft deletion and rollback documentation, and structural defenses against untrusted content.
- [ ] **E18 Single-goal edits:** make each commit or patch exactly one independently verifiable and reversible behavioral change.
- [ ] **E19 Edit-test cadence:** run the full test suite after each behavioral change to existing code and document expected test counts at each stage.
- [ ] **E21 Staged deployment:** deploy shared multi-tenant changes to the operator's own tenant first, verify and gate rollout to other tenants.
- [ ] **E23 API boundary discipline:** implement within existing boundaries without bypasses or escape hatches, and a change to a public interface states `Interface change:` in the PR's first line with what changes and who uses it instead of waiting for approval.
- [ ] **E25 Move files by reference:** pass file paths, upload handles or URLs instead of model-relayed bytes, return size and hash for verification, and write large outputs to a file with its path and summary.
- Every Done-when or acceptance criterion in the work order is shown to be met in the diff, its tests or the supplied check output (for example, a required dependency is actually added, or a required axe report or threshold decision is produced and asserted). A criterion that is left unmet, explained
- Any code path that turns a failure into published output (an 'unavailable', 'unverified', null or skipped record) catches only the specific upstream data condition it names. Missing credentials, missing local files and programming errors, including strict zip length mismatches, must fail the operation rather than become data findings. Catching ValueError broadly is insufficient: distinguish the documented upstream condition from unrelated failures.
