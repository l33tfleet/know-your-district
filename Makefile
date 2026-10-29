.PHONY: help sync check lint format typecheck imports browsers test evals run smoke golden data data-check snap-check links

BASE_URL ?= http://127.0.0.1:8000
HOST ?= 127.0.0.1
PORT ?= 8000
UV ?= uv

help:
	@echo "make sync                     install pinned dependencies (uv sync --locked)"
	@echo "make links                    check program URLs live (never refresh verification dates)"
	@echo "make check                    ruff, pyright strict, import-linter, pytest, evals"
	@echo "make run                      serve the app on http://$(HOST):$(PORT)"
	@echo "make smoke BASE_URL=<url>     check a running app (GET /healthz -> 200)"
	@echo "make format                   apply ruff fixes and formatting"
	@echo "make boundaries               rebuild State shapes, TIGER evidence and real fact-key proof"
	@echo "make data                     build cited ACS facts (optional CENSUS_API_KEY)"
	@echo "make golden                   fetch and atomically generate 300 independent ACS cases"

links:
	$(UV) run python -m etl.programs

data:
	$(UV) run python -m etl.build --sources data/sources

data-check:
	$(UV) run python -m etl.build --check

sync:
	$(UV) sync --locked

check: lint typecheck imports browsers test evals data-check snap-check

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format:
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck:
	$(UV) run pyright

imports:
	$(UV) run lint-imports --no-cache

# Headless Chromium for the browser checks in tests/regressions/test_wo122_browser_checks.py.
browsers:
	$(UV) run playwright install chromium

test:
	$(UV) run pytest tests --ignore=tests/evals

# Evals live in tests/evals/. An empty suite passes (pytest exit 5 = no tests collected).
evals:
	@$(UV) run pytest tests/evals; rc=$$?; \
	if [ $$rc -eq 5 ]; then echo "evals: no eval cases yet"; exit 0; fi; exit $$rc

run:
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT)

smoke:
	$(UV) run python scripts/smoke.py $(BASE_URL)

golden:
	$(UV) run python -m scripts.generate_golden

.PHONY: boundaries
# A supplied local collection retains the offline structural validator.
boundaries:
ifneq ($(strip $(BOUNDARIES_FILE)),)
	$(UV) run python -m etl.boundaries "$(BOUNDARIES_FILE)"
else
	$(UV) run python -m etl.boundaries.build $(BOUNDARIES_ARGS)
endif

# Offline SNAP coverage, independent district golden and dated referral evidence.
snap-check:
	$(UV) run python -m scripts.independent_snap
