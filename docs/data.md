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

The current scaffold loads and distributes no datasets:
[`etl/__init__.py`](../etl/__init__.py) is a placeholder and
[`data/`](../data/) contains only its README. The table records the
terms for all ACS products specified above, not a claim that they are loaded.
No State dataset, district boundary file or program dataset is currently used;
the district-plan description below is not a separately loaded dataset.
The repository's MIT software licence does not license third-party data.

| Dataset | Publisher | Licence or terms | Attribution line |
|---|---|---|---|
| ACS 2020–2024 5-year Detailed Tables (B and C tables listed below) | U.S. Census Bureau | U.S. public domain, federal government work ([17 U.S.C. § 105](https://www.govinfo.gov/content/pkg/USCODE-2022-title17/html/USCODE-2022-title17-chap1.htm#sec105)); [Census citation guidance](https://www.census.gov/about/policies/citation.html) | Source: U.S. Census Bureau, 2020–2024 ACS 5-Year Estimates, Detailed Tables, [table ID and title], [geography], https://api.census.gov/data/2024/acs/acs5, accessed [date]. |
| ACS 2020–2024 5-year Data Profiles (DP04, DP05) | U.S. Census Bureau | U.S. public domain, federal government work ([17 U.S.C. § 105](https://www.govinfo.gov/content/pkg/USCODE-2022-title17/html/USCODE-2022-title17-chap1.htm#sec105)); [Census citation guidance](https://www.census.gov/about/policies/citation.html) | Source: U.S. Census Bureau, 2020–2024 ACS 5-Year Estimates, Data Profiles, [table ID and title], [geography], https://api.census.gov/data/2024/acs/acs5/profile, accessed [date]. |
| ACS 2020–2024 5-year Subject Tables (S tables listed below) | U.S. Census Bureau | U.S. public domain, federal government work ([17 U.S.C. § 105](https://www.govinfo.gov/content/pkg/USCODE-2022-title17/html/USCODE-2022-title17-chap1.htm#sec105)); [Census citation guidance](https://www.census.gov/about/policies/citation.html) | Source: U.S. Census Bureau, 2020–2024 ACS 5-Year Estimates, Subject Tables, [table ID and title], [geography], https://api.census.gov/data/2024/acs/acs5/subject, accessed [date]. |

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
   `-555555555` (MOE: controlled, not sampled) and `-222222222`. They are never
   figures; map each to "not available" (or "controlled") before anything
   computes with it. Medians can also be top- or bottom-coded (e.g. rent or
   income at the table's limit); say so when that happens.
