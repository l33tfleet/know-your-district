# Evals

Eval cases for the chat agent and the data traps in `docs/data.md`, one
pytest file per behavior (`test_*.py`). `make evals` (part of `make check`)
runs them; an empty suite passes.

An eval checks behavior end to end: given a district and a question, the brief
or the chat reply must cite its figures, show uncertainty in words, take every
number from a tool result, and follow the product rules in `AGENTS.md`.
Evals must run offline and deterministically in CI (recorded model responses
or a stub model), so `make check` never needs a network or an API key.
