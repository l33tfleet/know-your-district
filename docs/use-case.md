# Use case: Know Your District (compact)

Source: HAIC 2026 Technology Use Case, "Know Your District: An AI Agent for Hawaiʻi's Legislative District Resident
Profiles", https://haic.hawaii.gov/wp-content/uploads/2026/10/HAIC_Use_Case_Know_Your_District_AI_Agent_2026.pdf
(sha256 1283f8a2…793305e, 6 pages, read 2026-10-28). Wording kept close to the original; IDs are ours, `pN` = PDF
page. Cite as `UC-<id>`. The PDF wins over this copy.

Champion: DBEDT Research & Economic Analysis Division (READ); coordinated by ETS. Subject-matter contact: Chief State
Economist, questions only via Slack #c_dbedt_agent. (p1)

## Problem (p1-2)
- C1 Legislators and officials have no fast, reliable way to understand a district's resident profile or which
  existing state and federal programs could serve its constituents, so eligible residents miss programs that exist.
- C2 51 House + 25 Senate districts, each its own mix of income, jobs, housing costs, ages, household situations.
- C3 Data is spread across DBEDT, DOTAX, UHERO and federal agencies, mostly by county, tract or state, not district.
- C4 The question "Who lives in my district, and what help is available to them?" has no single complete, sourced
  answer, so outreach is hard to target and many who qualify never enroll.
- C5 Today: search several sources by hand; match county/tract/ZIP data to districts, often by hand; research
  programs separately. Slow, inconsistent across offices, rarely connects the profile to specific programs.

## Assumptions (p2)
- A1 Public, aggregated data only; no individual taxpayer or confidential records.
- A2 Most datasets aren't by district: apportion or crosswalk tract/ZIP/county data and explain the method.
- A3 Small districts or groups may have large margins of error or be suppressed; say so, don't overstate precision.
- A4 Boundaries follow the latest reapportionment; use official boundary files.
- A5 Program info (eligibility, contacts, links) changes; the solution needs a way to keep it current.

## Users (p2)
- U1 Primary: the 76 state legislators (51 House, 25 Senate) and their staff.
- U2 Secondary: government officials doing outreach or policy planning.

## Business rules (p3)
- B1 Every figure cites source, year and geography, and says when it was estimated or apportioned.
- B2 Say when data is unavailable, outdated or uncertain rather than guess.
- B3 Program recommendations are informational; the administering agency decides eligibility; link the official
  program source.
- B4 Populations, not individuals; never identify or infer anything about specific residents.
- B5 Nonpartisan: data and programs, no political commentary.
- B6 WCAG 2.1 AA, plain language, correct ʻokina and kahakō in Hawaiian place names.

## Special requirements (p3)
- Q1 Publicly available data only.
- Q2 Responsible AI: answers grounded in the cited datasets (no unsupported figures), with a clear way to check
  sources; follow State of Hawaiʻi AI and data guidance.
- Q3 Confirm terms of use for third-party data (e.g. datatrove.ai, UHERO) before use.
- Q4 No state credentials or non-public systems.
- Q5 Model validation: testing protocols that show mapping and eligibility results are accurate.

## Platforms (p3)
- P1 Current: reports, spreadsheets, online data tools from DBEDT/READ, DOTAX, UHERO, federal agencies (Census API).
- P2 Desired: web-based AI agent (chat) with district summaries; ESRI ArcGIS may show boundaries and data layers;
  own AI tools and stack, favoring components the State could evaluate later.

## Data (p4)
- D1 DBEDT/READ economic and demographic data, incl. the State of Hawaiʻi Data Book.
- D2 DOTAX aggregated public tax statistics.
- D3 UHERO public data and reports.
- D4 Census, incl. ACS tables by state legislative district.
- D5 Other federal statistics (BLS, BEA).
- D6 datatrove.ai public data.
- D7 Official legislative district boundary files.
- D8 Public program and eligibility information (state, county, federal).
- D9 Collect no new resident data; a structured program/eligibility inventory from public sources is expected.

## Outputs (p4)
- R1 Summary per House and Senate district: population and age (incl. kūpuna), household income and poverty,
  employment and industries, housing costs, other indicators DBEDT/READ prioritizes.
- R2 District vs its county and the state.
- R3 Populations likely eligible for existing programs, beside current uptake where data exists: where outreach could
  help most.
- R4 Map views of boundaries and key indicators (ESRI).
- R5 Exportable summary (PDF or printable one-pager) with sources.

## Basic flow (p4)
- F1 Pick or name a district, or ask in plain language (e.g. "How many kūpuna in my district live on fixed
  incomes?").
- F2 Agent retrieves the data from DBEDT, DOTAX, UHERO, federal and other public sets for that district.
- F3 Clear socio-economic summary with sources, years, margins of error, limitations.
- F4 Recommends existing state, county, federal programs for the district's populations, linked to official info.
- F5 Follow-up questions, map view, export.

## Goal and value (p5)
- G1 A plain-language AI agent that accurately describes any district's socio-economic make-up and points to
  existing programs, raising uptake of programs residents already qualify for.
- V1 Faster, consistent profiles without custom analysis requests.
- V2 Better-targeted outreach: more eligible residents get help that's already funded.
- V3 Better-informed policy and budget decisions from district-level data.
- V4 A reusable foundation DBEDT/READ can extend with new datasets.

## Success (p5)
- S1 A legislative office gets an accurate, sourced profile of any district in minutes, not days.
- S2 DBEDT/READ experts check a sample of answers and confirm figures and citations.
- S3 Test users find the programs relevant and can follow them to official sources.
- S4 At least one population + program combination where outreach could measurably increase uptake.

## Committee notes (p5)
- X1 Data candidates: DBEDT/READ data warehouse and Data Book; DOTAX tax statistics; UHERO; ACS by state legislative
  district; BLS and BEA regional; datatrove.ai; ESRI/ArcGIS Living Atlas layers. Links:
  https://tax.hawaii.gov/stats/a5_1annual/ · https://tax.hawaii.gov/stats/a5_3txcolrpt/ ·
  https://tax.hawaii.gov/data-dashboard/ · https://dbedt.hawaii.gov/economic/ ·
  https://www.census.gov/programs-surveys/acs/data.html
- X2 Possible co-sponsors: DBEDT/READ (champion), UHERO, ESRI, datatrove.ai, Aloha United Way, DOTAX, Department of
  Human Services and other agencies whose programs the agent recommends.
