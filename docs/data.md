# Data: indicators, vintage, reliability and known traps

Later work orders cite this file instead of repeating it. Product rules are in
`AGENTS.md`; this file holds the data facts.

## Source and vintage

- **Source:** U.S. Census Bureau, American Community Survey (ACS) **5-year
  estimates, 2020–2024**. One vintage for every figure; it is pinned, never
  "latest".
- **API base:** `https://api.census.gov/data/2024/acs/acs5`
  - Detailed tables (B, C): `https://api.census.gov/data/2024/acs/acs5`
  - Data Profile (DP): `https://api.census.gov/data/2024/acs/acs5/profile`
  - Subject tables (S): `https://api.census.gov/data/2024/acs/acs5/subject`
- Each estimate `…E` (or percent `…PE`) has a margin of error `…M` (or `…PM`)
  at the **90% confidence level**. Always fetch both.

## Data licences

The ETL ([`etl/census.py`](../etl/census.py)), configured by
[`config.toml`](../config.toml), fetches ACS 2020–2024 5-year Detailed,
Data Profile and Subject tables from the Census API. The fact build publishes
the validated SQLite database at [`data/facts.db`](../data/facts.db), using
[`data/schema.sql`](../data/schema.sql), with a canonical TSV and checksum
sidecar. This replaces the earlier "no built database is committed" state.
The boundary build reads this database without modifying it. The table records
the terms for these ACS products.
The boundary build also fetches the State's 2022 House and Senate district
layers and compares them with Census TIGER/Line 2022. The published State
geometry and evidence are in [`data/geo/`](../data/geo/); these shapes are not
ACS observations. Program reference data is in `data/programs.yaml`.
The repository's MIT software licence does not license third-party data.

| Dataset | Publisher | Licence or terms | Attribution line |
|---|---|---|---|
| ACS 2020–2024 5-year Detailed Tables (B and C tables listed below) | U.S. Census Bureau | U.S. public domain, federal government work ([17 U.S.C. § 105](https://www.govinfo.gov/content/pkg/USCODE-2022-title17/html/USCODE-2022-title17-chap1.htm#sec105)); [Census citation guidance](https://www.census.gov/about/policies/citation.html) | Source: U.S. Census Bureau, 2020–2024 ACS 5-Year Estimates, Detailed Tables, [table ID and title], [geography], https://api.census.gov/data/2024/acs/acs5, accessed [date]. |
| ACS 2020–2024 5-year Data Profiles (DP04, DP05) | U.S. Census Bureau | U.S. public domain, federal government work ([17 U.S.C. § 105](https://www.govinfo.gov/content/pkg/USCODE-2022-title17/html/USCODE-2022-title17-chap1.htm#sec105)); [Census citation guidance](https://www.census.gov/about/policies/citation.html) | Source: U.S. Census Bureau, 2020–2024 ACS 5-Year Estimates, Data Profiles, [table ID and title], [geography], https://api.census.gov/data/2024/acs/acs5/profile, accessed [date]. |
| ACS 2020–2024 5-year Subject Tables (S tables listed below) | U.S. Census Bureau | U.S. public domain, federal government work ([17 U.S.C. § 105](https://www.govinfo.gov/content/pkg/USCODE-2022-title17/html/USCODE-2022-title17-chap1.htm#sec105)); [Census citation guidance](https://www.census.gov/about/policies/citation.html) | Source: U.S. Census Bureau, 2020–2024 ACS 5-Year Estimates, Subject Tables, [table ID and title], [geography], https://api.census.gov/data/2024/acs/acs5/subject, accessed [date]. |

Boundary source attribution is separate from the ACS figure citations:

| Dataset | Publisher | Terms and credit |
|---|---|---|
| 2022 State House and Senate district layers, ArcGIS layers 33 and 34 | State of Hawaiʻi Office of Elections / Hawaiʻi Statewide GIS Program | [Source service](https://geodata.hawaii.gov/arcgis/rest/services/AdminBnd/MapServer). Preserve each layer's verbatim credit in `house.credit.txt` and `senate.credit.txt`; the repository software licence does not grant data rights. Exact query, retrieval date, plan and server generalization method are in each chamber's `.provenance.json`. |
| TIGER/Line 2022 Hawaiʻi SLDL and SLDU | U.S. Census Bureau | Comparison inputs, not the displayed shapes; [TIGER/Line documentation and use limitations](https://www.census.gov/programs-surveys/geography/technical-documentation/complete-technical-documentation/tiger-geo-line.html). Exact archive URLs accompany each overlay result. |

Attribution lines are templates: replace bracketed fields with the actual table,
geography and access date. For derived figures, identify Census as the source of
the original data and state the app's derivation method separately; analysis
conclusions are the performing party's responsibility, per the Census guidance.

## Geographies (81 in all)

Districts are the **2022 plan** (the Hawaiʻi Reapportionment Commission's 2022
plan, used since the 2022 elections). All requests use `in=state:15` (Hawaiʻi).

| Geography | API `for=` | Count |
|---|---|---|
| State House districts | `state legislative district (lower chamber):*` | 51 |
| State Senate districts | `state legislative district (upper chamber):*` | 25 |
| Counties: Hawaiʻi (001), Honolulu (003), Kauaʻi (007), Maui (009) | `county:*` | 4 |
| State of Hawaiʻi | `state:15` (no `in=`) | 1 |

**Kalawao County (005) is left out.** It is the Kalaupapa settlement on
Molokaʻi, home to fewer than a hundred people and administered by the state
Department of Health rather than a county government. Its ACS margins of error
are as large as or larger than its estimates, so nearly every figure would be
"use with caution" or unavailable, and no legislator's brief is about it alone.
Its residents are still counted in the state figures and in the House and
Senate districts that contain it. Maui County figures do not include Kalawao.

## Indicators

The ETL must check each variable's label in
`<base>/variables/<VARIABLE>.json` (or `/profile/…`, `/subject/…`) before
loading, and stop if it does not match the meaning below (see the traps).

| Indicator | Variable | Table | Endpoint |
|---|---|---|---|
| Total population | B01003_001E | B01003 | detailed |
| Share age 65+ | DP05_0024PE | DP05 | profile |
| Median household income | B19013_001E | B19013 | detailed |
| Poverty rate | S1701_C03_001E | S1701 | subject |
| Poverty rate, age 65+ | S1701_C03_010E | S1701 | subject |
| Unemployment rate | S2301_C04_001E | S2301 | subject |
| Households receiving SNAP | B22010_002E | B22010 | detailed |
| Share of households receiving SNAP | S2201_C04_001E | S2201 | subject |
| Households with Social Security income | B19055_002E | B19055 | detailed |
| Households with retirement income | B19059_002E | B19059 | detailed |
| Renters paying 30%+ of income on rent | DP04_0142PE | DP04 | profile |
| Median gross rent | B25064_001E | B25064 | detailed |
| Uninsured rate | S2701_C05_001E | S2701 | subject |
| Share with a disability | S1810_C03_001E | S1810 | subject |
| Limited-English households | S1602_C04_001E | S1602 | subject |
| Households with no vehicle | B08201_002E | B08201 | detailed |
| Ratio of income to poverty level, by bracket | C17002_001E–C17002_008E | C17002 | detailed |

C17002 brackets (ratio of income to poverty level in the past 12 months):

| Variable | Bracket |
|---|---|
| C17002_001E | Total (population for whom poverty status is determined) |
| C17002_002E | **Under 0.50** (not "under 1.00") |
| C17002_003E | 0.50 to 0.99 |
| C17002_004E | 1.00 to 1.24 |
| C17002_005E | 1.25 to 1.49 |
| C17002_006E | 1.50 to 1.84 |
| C17002_007E | 1.85 to 1.99 |
| C17002_008E | 2.00 and over |

## Reliability

Coefficient of variation from the published 90% margin of error:

```
CV = (MOE / 1.645) / estimate
```

| CV | Flag shown in words next to the figure |
|---|---|
| ≤ 15% | reliable |
| > 15% and ≤ 30% | moderate: use with care |
| > 30% | use with caution |

- An estimate of 0, or a missing MOE, has no CV: show it as "use with caution".
- The outreach indicators (poverty 65+, limited English, no vehicle, uninsured)
  cross the caution line in many House districts. **Caution is a normal state,
  not an error**: show the figure with its flag, don't hide it.
- The MOE of a sum of estimates is approximated as `sqrt(MOE₁² + MOE₂² + …)`
  (Census Bureau guidance); say "derived" in the method when this is used.
  A controlled MOE (annotation `*****`) counts as 0 in that sum; any other
  missing MOE leaves the derived MOE missing.
- The MOE of a derived proportion `p = X / Y` (numerator X a subset of
  denominator Y, both in one universe and one geography) uses the ACS handbook
  proportion formula `sqrt(MOE_X² - p² · MOE_Y²) / Y`. When the radicand
  `MOE_X² - p² · MOE_Y²` is negative, use the ratio formula
  `sqrt(MOE_X² + p² · MOE_Y²) / Y` instead, and name the formula used in the
  method. A zero denominator is "not computed", never 0%.

## Known traps (each becomes an eval case in `tests/evals/`)

1. **National poverty thresholds.** ACS poverty status uses the national Census
   poverty thresholds. Hawaiʻi programs use the higher Hawaiʻi HHS poverty
   guidelines, so ACS counts below a poverty multiple **understate** who may be
   eligible. Present them as a lower bound, in words.
2. **Bracket edges.** Poverty-ratio brackets break at 0.50, 1.00, 1.25, 1.50,
   1.85 and 2.00. Use and name the nearest bracket edge (e.g. "below 1.85 times
   the poverty level" for a 185% program); **never interpolate** within a
   bracket. `C17002_002E` is "under 0.50", an easy label to get wrong.
3. **Benefit undercount.** Survey answers undercount people receiving benefits
   (SNAP, Social Security, public assistance). Say so next to those figures.
4. **Data Profile codes drift.** DP (and S) variable codes change meaning
   between vintages. Pin the vintage and assert each variable's label text
   before loading. In particular, confirm `DP05_0024PE` is "65 years and over"
   and that `DP04_0142PE` is the 30%-or-more rent share; DP04 publishes gross
   rent as a percentage of household income in brackets, and if the variable
   is only one bracket the 30%+ share is the sum of the 30.0–34.9% and 35.0%+
   percents, which the method must say.
5. **District plan and count.** Districts are the 2022 plan: 51 House and 25
   Senate districts, plus 4 counties (Kalawao left out, see above) and the
   state, 81 geographies in all. A load with any other count fails.
6. **Annotation values.** The API returns sentinel numbers instead of nulls,
   e.g. `-666666666` (estimate not available), `-999999999`, `-888888888`,
   `-555555555` (MOE: controlled, not sampled), `-222222222` and `-333333333`
   (median in an open-ended interval, top- or bottom-coded). They are never
   figures; map each to "not available" (or "controlled") before anything
   computes with it. For `-333333333`, preserve the open-ended-interval wording
   (e.g. rent or income at the table's limit) in the method.

## WO59 fact contract: reconciliation of #23 and #24

The 17 logical indicators above are groups, not 17 scalar database rows.
This contract replaces #24's literal 81 × 17 row target while preserving its
exclusion of derived figures: 15 single-cell indicators + eight C17002 cells
(including the total) + two rent components = 25 published scalar rows per
geography, or 2,025 rows across 81 geographies for one vintage. No poverty
bracket is discarded, combined or interpolated to meet a row count.

The rent entry above names a logical output, not the meaning of 0142 alone:
DP04_0141PE/PM is 30.0–34.9%; DP04_0142PE/PM is 35.0% or more. Store each
published pair separately. Both use occupied units paying rent excluding units
where GRAPI cannot be computed. The 30%+ sum is deferred to WO-6, with method
explicitly derived and MOE sqrt(MOE₁² + MOE₂²); it is never a published fact.
The independent WO42 metadata review confirms these two component meanings.

The fact/golden join key is (variable, geography, vintage), not a display label
or group ordinal. Each oracle scalar maps directly to one fact with its MOE;
C17002 maps to eight separate comparisons and rent to two. A logical golden
case containing several cells expands to these same keys. A derived rent case
cannot be compared to 0142 alone and belongs in WO-6's derived checks.
The "about 300" golden sample size is not a fact-table cardinality requirement.
Geography keys are qualified: house:15:001:2022, senate:15:001:2022,
county:15:001 and state:15, preserving leading zeros and district plan.

Scope of this step: config.toml, etl/indicators.py, app/models.py,
data/schema.sql, this contract, and new regression tests. Fetching, metadata
validation, database building, golden generation and UI rendering are later
steps; the oracle stays independent. Config pins the ACS year and vintage;
endpoint URLs use the year placeholder. No database or observations ship here.

## Boundary identity and validation (WO-66, from WO-47)

`etl.boundaries.DistrictId` requires a chamber and normalizes one to three ASCII digits or integers to `house-01`…`house-51` or `senate-01`…`senate-25`; `census_code` preserves three digits. State and county keys are outside this contract. Boundary keys map explicitly to WO59 fact keys: `house-01` → `house:15:001:2022`, likewise for Senate; these are distinct representations, not interchangeable join strings.
The local GeoJSON FeatureCollection requires provenance: HTTP/S `source_url`, ISO calendar `retrieved_on` (YYYY-MM-DD), nonblank `vintage` and `method`, and `plan_year` 2022. Features have only `chamber` and `district` properties. Map source attributes before validation.
Geometry must be a nonempty Polygon or MultiPolygon with finite longitude/latitude pairs, closed rings and three distinct vertices per ring. Duplicate normalized keys fail. Structural validation does not prove topology, coverage, projection correctness or official district correspondence.
Run `make boundaries BOUNDARIES_FILE=<local.geojson>` offline to validate and print canonical keys. `tests/regressions/fixtures/wo47_boundaries.geojson` is synthetic. Partial collections are allowed here; production loads must enforce the district counts above.
**WO-3 (#24) is a prerequisite for the real-database join proof.** That work must deliver the real fact table and reconcile boundary keys with the qualified fact geography keys before proving exact House and Senate key-set equality, detecting missing and extra keys in either direction. The database is now delivered at `data/facts.db`; the default boundary build
checks it and publishes the result in `fact-keys.md`.


## Production boundary build (WO-80, final step of #27)

`make boundaries` fetches both State layers through `etl.boundaries.state`,
validates and exports qualified identities through `etl.boundaries.production`,
and uses `etl.boundaries.overlay` for the TIGER archive validation and equal-area
comparison. It rebuilds `data/geo/house.geojson` and `senate.geojson`, each below
one megabyte, with separate provenance and verbatim credit sidecars. The
**displayed source is the State**, with its server generalization preserved;
TIGER never replaces a State shape. The build uses no ACS values or model calls.
The app serves district briefs; this work does not add a map UI.

`overlay.md` reports every district, its source query, retrieval date, plan,
method and TIGER archive URL. Agreement is intersection / union in EPSG:6933,
using the prepared overlay engine without snapping, buffering or repairs.
Every result below the 99% threshold appears in `mismatch.md` with its computed
shortfall in percentage points. Invalid topology and computation failures are
listed as **UNVERIFIED**, with their errors and no invented agreement or
shortfall. They are exceptions requiring review, not successful overlays.
Invalid TIGER archives fail the build before publishing new artifacts.

The published run has five districts at or above the threshold, 55 below it,
and 16 unverified; the per-district evidence, rather than this summary, is the
record of the comparison. The State's generalized geometry has topology errors
in some districts; the prepared overlay also encounters interval computation
failures. No geometry has been silently repaired to improve agreement.

A successful build additionally requires exact equality with distinct district
geography keys read from the **actual** SQLite `facts` table in read-only mode.
`fact-keys.md` records the database path, checksum on success, and missing/extra
key evidence on failure. State/county keys are excluded; both chambers and both
set differences are checked. This is a geography-key proof, not proof of fact
row completeness or geographic correspondence. **#24 must supply the real
database**: no database is generated from the boundary IDs as a substitute.
The default run now reads the delivered `data/facts.db` and publishes the real
join proof alongside shapes and overlay evidence. A missing or mismatched
database still exits nonzero and publishes the failed-join evidence.

Operator commands:

```sh
make boundaries
make boundaries BOUNDARIES_ARGS='--facts-db /path/to/real/facts.sqlite'
make boundaries BOUNDARIES_FILE=/path/to/normalized.geojson
# Offline replay of downloaded inputs (not synthetic production data):
make boundaries BOUNDARIES_ARGS='--source-dir /path/to/downloads --facts-db /path/to/real/facts.sqlite'
```

`--source-dir` contains unchanged `state-house.json`, `state-senate.json`,
`tl_2022_15_sldl.zip` and `tl_2022_15_sldu.zip`. `--output-dir` selects an
alternative artifact directory. An explicitly supplied `BOUNDARIES_FILE`
retains the earlier offline structural validation and canonical key output,
including support for partial collections, with no network or database access.
Offline regression builds use synthetic State responses, actual shapefile ZIP
encoding and temporary SQL tables; their join passes are test evidence only.

## ZIP tax and population crosswalk contracts (#168, step 1 of #134)

These additive, offline contracts live in `etl/zip_contract.py`. They do not
change ACS facts, existing geometry, the SQLite schema or runtime readers.
`read_tax`, `read_crosswalk` and `read_records` read normalized JSON arrays,
validate records and reject duplicate keys. Upstream adapters normalize source
labels and suppression markers before calling these readers. Steps 2–4 return
validated records; step 5 alone writes outputs. No tax observations ship here.
Pydantic, pyproj and pyshp are pinned to the versions in `uv.lock` for replay.

- Tax identity is (ZIP, measure, filing status, tax year). Preserve every source
  year and filing-status category separately, including comparison years;
  never replace the tax year with the retrieval year. Each row carries units,
  decimal value, published/suppressed/unavailable status, table, source URL and
  retrieval date. A suppressed or unavailable value is null, never zero.
  These are aggregate administrative tax-return statistics, not ACS estimates
  of households or residents. They carry no invented ACS MOE or CV flag.
- **ZIP ≠ ZCTA.** Postal ZIP codes describe delivery routes; Census ZCTAs are
  generalized statistical areas, and not every ZIP has a corresponding ZCTA
  ([Census definition](https://www.census.gov/programs-surveys/geography/guidance/geo-areas/zctas.html)).
  Keep five ASCII digits, including leading zeros. ZCTA geometry has its own
  2020 vintage, source URL and retrieval date. A matching code alone does not
  establish geographic equivalence. Preserve unmappable ZIPs with reasons;
  never fabricate geometry or silently drop them.
- Crosswalk rows identify ZCTA and chamber-qualified 2022 district, intersection
  population, **both population denominators** (whole ZCTA and whole district),
  population year 2020, source URL and retrieval date. The method is exactly
  `population-weighted (2020 blocks)`. Each share divides the intersection by
  its respective denominator. Zero denominators are unmappable, not zero
  shares. Existing overlay areas and county area normalization cannot supply
  population weights. Geometry failures described above remain review failures;
  do not silently repair shapes or substitute area fractions.
- **Medians are non-apportionable.** Never multiply ZIP median AGI by a crosswalk
  share, sum medians, or label a weighted average of ZIP medians a district
  median. Published ZIP observations remain separate from derived crosswalks.

Source rights and attribution for subsequent builds:

| Input | Terms and required evidence |
|---|---|
| Hawaiʻi Department of Taxation individual income tax tables | [Published report example](https://files.hawaii.gov/tax/stats/stats/indinc/2022indinc.pdf). No redistribution licence is asserted here; public access is not a licence grant. Record report-specific terms and permission before redistributing source files. Attribute Department of Taxation, report/table, tax year, filing status, ZIP, units, exact URL and retrieval date. Preserve suppression notes. |
| Census 2020 ZCTA/block geometry and block population | Federal government works are public domain under the federal-work terms cited above. Retain [TIGER/Line documentation and limitations](https://www.census.gov/programs-surveys/geography/technical-documentation/complete-technical-documentation/tiger-geo-line.html); attribute Census, product/table, 2020 vintage, geography, exact URL and retrieval date. These are decennial inputs, not ACS. |
| State district geometry | Retain the State service terms and verbatim layer credits described above; the repository MIT licence grants no third-party data rights. |

Step 5 must package full outputs (including the tax TSV exceeding the review
line budget) as reproducible build artifacts, not truncated samples in code PRs.
Include input URLs and retrieval dates, dependency lock, replay command, input
and output SHA-256 checksums, row counts, suppression/year/status checks,
unmappable reasons and geometry/crosswalk review evidence. Keep code PRs below
12 files and 400 changed lines. This step defines contracts, not that publisher.

## Supplemental population acquisition plan (#202, step 1 of #147)

`etl/population_variables.py` inventories populations separately from the WO59 indicator contract. `POPULATION_VARIABLES` lists **all 70
required published estimate cells**, including denominators; acquire each corresponding 90% MOE and both annotations too. Main currently
publishes only three indicators (243 rows), so membership in the 25-cell indicator registry does not establish availability in `facts.db`.
This step adds no observations, YAML, analysis or brief section; subsequent steps validate developer-maintained YAML, derive shares and
refresh artifacts through `etl/build.py`. The SQLite schema, fact keys and TSV stay the same. The full refresh still requires the
size-policy resolution described in #202; do not truncate observations to fit a review cap.

All cells below are U.S. Census Bureau **2020–2024 ACS 5-year** published cells, using the endpoints and 2022-plan geographies above. Native
geography is the published district (also county/state), never an area allocation or estimated crosswalk. Counts describe survey-time age,
race, household composition and disability; income, poverty, Social Security, retirement and SNAP refer to the past 12 months at each
interview, not one calendar year. Rent is monthly gross rent relative to one-twelfth of household income in the past 12 months. Comparisons
will use the same numerator and denominator in district, county and state. Every plus sign below means a later **derived** sum with the
sum-MOE method above, never a new published fact. No marginal percentages are multiplied to infer joint cells.

Notation: table prefixes apply to every listed suffix; ranges are inclusive; all suffixes designate estimate `E` cells. This table
enumerates the complete numerator/denominator inventory, not merely additions to existing indicators.

| Population / unit | Table: numerator cells | Denominator cells / share meaning | Universe and exclusions |
|---|---|---|---|
| Children under 5 / persons | B01001: 003 + 027 | B01001: 001; share of total population | Total population; excludes ages 5+ from numerator; both sexes, including group quarters. |
| Children under 18 below poverty / persons | B17001: 004–009 + 018–023 | B17001: 004–009 + 018–023 + 033–038 + 047–052; poverty rate among children whose poverty status is determined | Poverty-status universe below; excludes adults and children without determined poverty status. |
| Households with children under 18 / households | B11005: 002 | B11005: 001; share of all households | Households; includes family and nonfamily households with any resident under 18, not only own children; excludes group quarters. |
| Native Hawaiian alone or in combination / persons | B02019: 002 | B01001: 001; share of total population | B02019 universe: Native Hawaiian and Other Pacific Islander alone or in any combination reporting one or more responses; excludes residents without a Native Hawaiian response from numerator. |
| Kūpuna (65+) / persons | B01001: 020–025 + 044–049 | B01001: 001; share of total population | Total population; both sexes, including group quarters; excludes under 65 from numerator. |
| Residents 65+ below poverty / persons | B17001: 015 + 016 + 029 + 030 | B17001: 015 + 016 + 029 + 030 + 044 + 045 + 058 + 059; poverty rate among residents 65+ with determined status | Poverty-status universe; excludes under 65 and undetermined status, rather than using all older residents as denominator. |
| Households with a person 65+ living alone / households | B11007: 003 | B11007: 001; share of all households | Households; one-person households with a resident 65+; excludes group quarters and older people living with others. Not a share of all older people. |
| Households with Social Security income / households | B19055: 002 | B19055: 001; share of all households | Households; any member reporting Social Security, including survivor/disability benefits; excludes SSI-only receipt; no age or income-adequacy inference. |
| Households with retirement income / households | B19059: 002 | B19059: 001; share of all households | Households; retirement, survivor or disability pensions and other retirement income; excludes Social Security and SSI as retirement income; no age inference. |
| People with a disability / persons | S1810: C02_001 | S1810: C01_001; share of civilian noninstitutionalized population | Civilian noninstitutionalized population; excludes active-duty military and institutional residents. |
| Renter households paying 30%+ of income on rent / households | DP04: 0141 + 0142 (counts, not PE) | DP04: 0136; share of occupied units paying rent with computable GRAPI | Occupied units paying rent; excludes units where GRAPI cannot be computed, including no-cash-rent units. One household per occupied unit; never a count of people. |
| Residents below 200% of poverty / persons | C17002: 002–007 | C17002: 001; share of population with determined poverty status | Poverty-status universe; excludes ratio 2.00+ and undetermined status. No bracket interpolation. |
| Households below poverty reporting no SNAP / households | B22003: 006 | B22003: 003 + 006; nonreceipt share among households below poverty | Households; joint income/nonreceipt cell; excludes at-or-above-poverty households from both terms. Does not establish unmet need or eligibility. |

The person-level poverty universe excludes institutionalized people, people in college dormitories or military group quarters, and unrelated
individuals under 15. Household tables exclude people outside households. Census national poverty thresholds differ from Hawaiʻi HHS
guidelines: these counts are a **lower bound** for outreach, not program eligibility. Benefit receipt is self-reported and undercounted; say
this alongside SNAP and Social Security figures. B19055 and B19059 populations **overlap**: keep separate, never sum them, never call them
“fixed income,” and never describe the household counts as kūpuna.

Metadata evidence: [Census detailed groups](https://api.census.gov/data/2024/acs/acs5/groups.html),
[DP04](https://api.census.gov/data/2024/acs/acs5/profile/groups/DP04.html),
[S1810](https://api.census.gov/data/2024/acs/acs5/subject/groups/S1810.html). `config.toml` pins supplemental labels under
`[population_labels]`; `load_population_config` merges them into a private Census config; the regression test pins their independently
retrieved metadata digest. Live verification on 2026-10-29 passed for all 70 required cells plus the unselected Native Hawaiian alone cell,
with exact House (001–051) and Senate (001–025) key sets. Estimates are nonnegative; MOEs are nonnegative or explicitly controlled with the
Census annotation. Both Native Hawaiian alternatives were checked:
[B02016_002](https://api.census.gov/data/2024/acs/acs5/groups/B02016.html) is alone;
[B02019_002](https://api.census.gov/data/2024/acs/acs5/groups/B02019.html) includes combinations. B02019_001 is groups tallied, **not total
population**. Do not sum race tallies or add B02016_002 to B02019_002. The chosen label must also be used in later match explanations. The
broader NHPI fallback is unnecessary for this vintage; if detailed cells become unavailable, explicitly review the mapping to B02001_006 and
label it “Native Hawaiian and Pacific Islander” everywhere.

`verify_district_availability` holds the check: exact labels (checked by `CensusClient` before any data request), exact House and
Senate key sets, and a usable estimate, MOE and annotation for every cell in every district. The regression tests run it offline against
a stub on every `make check`. Replay it live as an operator step (requires `CENSUS_API_KEY`):

```sh
uv run python -m etl.population_variables
```
