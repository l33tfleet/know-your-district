# Know Your District

A public web tool for Hawaiʻi legislators and their staff to prepare a cited,
printable district brief and find public programs that may help.

**Start at the live app: [Know Your District](https://district.hawaiitechmentors.org).**
Choose House or Senate and a district number, then open the brief. No account
or API key is needed to use the site.

## What works today

- **76 district briefs:** all 51 State House and 25 State Senate districts in
  Hawaiʻi's 2022 plan ([geography inventory](docs/data.md#geographies-81-in-all)).
- **Three demographic figures:** total population, share age 65 and over, and
  median household income, alongside county and state comparisons. Each figure
  carries a citation with source, table ID, vintage, geography and method, a
  margin of error (MOE), and reliability in words: “reliable,” “moderate: use
  with care,” or “use with caution.” Source details are expandable.
- **SNAP outreach comparison:** the selected district, its county or counties,
  and the state show survey-reported households below the Census poverty level
  that reported no SNAP receipt in the past 12 months (ACS B22003). This is an
  outreach signal, not an eligibility gap or a count of currently unenrolled
  eligible households. Survey answers undercount benefit receipt; Census
  poverty thresholds differ from Hawaiʻi program guidelines.
- **Programs that may help:** program cards and SNAP outreach contacts link to
  official information. The agency decides eligibility. Start with the
  [official DHS SNAP page](https://humanservices.hawaii.gov/bessd/snap/) or
  [Aloha United Way 211](https://www.auw211.org/) for help finding services.
- **Print:** use the browser's Print command for a one-page brief with citations,
  uncertainty and program guidance, or save it as a PDF through the browser.

## Data sources and limits

Figures come from the U.S. Census Bureau **2020–2024 ACS 5-year estimates**:
B01003 (population), DP05 (age share), B19013 (household income) and B22003
(poverty and reported SNAP receipt). The published estimates and 90% MOEs are
built ahead of time into committed, read-only SQLite databases:
[`data/facts.db`](data/facts.db) and [`data/snap/facts.db`](data/snap/facts.db).
They are survey estimates for that period, not a live count of residents.

Local reference data includes [`data/programs.yaml`](data/programs.yaml) for
program descriptions and official sources, and
[`data/snap/referrals.json`](data/snap/referrals.json) for dated assistance
contacts and service-area limits. County comparisons use the committed
[`district/county mapping`](data/district_counties.tsv), derived from State
district and Census county boundaries. County values describe whole counties;
they are not allocated to districts. See the
[data licences and attribution table](docs/data.md#data-licences) for source
rights, and [data methods](docs/data.md) for uncertainty and known traps.

**Current limits:** chat, an interactive map and saved district folders are
unavailable. Ask/chat (#183) and folders (#155) are planned; their
implementation issues own subsequent documentation updates. Program guidance
supports outreach planning and referrals, not individual eligibility decisions.

## Run from a clean clone

You need [`uv`](https://docs.astral.sh/uv/) and `make`. Nothing else: there is
no database server to install. The data is a read-only SQLite file, built ahead
of time and committed under `data/`, and `uv`
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
