# Know Your District

A public web tool for Hawaiʻi legislators and their staff. Pick a State House
or Senate district and get a one-page, printable, cited brief of who lives
there, how sure the numbers are, and which public programs may help. A chat bar
edits the brief. Every figure comes from a published table (U.S. Census ACS
5-year first) and carries its source, table ID, vintage, geography and margin
of error.

Live site: https://district.hawaiitechmentors.org

> Status: scaffold. The app serves a placeholder home page and `/healthz`;
> district briefs come in later work orders.

## Run from a clean clone

You need [`uv`](https://docs.astral.sh/uv/) and `make`. Nothing else: there is
no database server to install. The data is a read-only SQLite file, built ahead
of time and committed under `data/` (from the data work orders on), and `uv`
fetches Python 3.12 if you don't have it.

```sh
git clone https://github.com/l33tfleet/know-your-district.git
cd know-your-district
uv sync
make run          # serves http://127.0.0.1:8000
```

Without `make`: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`.

## Test

```sh
make check                                  # ruff, pyright (strict), import-linter, pytest, evals
make smoke BASE_URL=http://127.0.0.1:8000   # against a running app: GET /healthz must return 200
```

## For contributors and agents

Read the [security and privacy note](docs/security-privacy.md) and the
[data licences and attribution table](docs/data.md#data-licences).

Read [`AGENTS.md`](AGENTS.md) first: product rules, stack pins, layout and
where tests go. Data sources, indicators and reliability rules are in
[`docs/data.md`](docs/data.md). The reviewer rubric is
[`.factory/review.md`](.factory/review.md).

## License

MIT, see [`LICENSE`](LICENSE).
