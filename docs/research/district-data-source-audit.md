# District data and benefit outreach: findings and path forward

> Copied into the product repo on 2026-10-29 from the team's planning notes (not public). Research guidance: where it disagrees with `AGENTS.md` or `docs/data.md`, those win. `AGENTS.md` is code-owned, so propose a decision in the PR and the Code Owner records it. Dated facts stay dated: recheck current official rules before shipping a referral.

Researched 2026-10-29 against the HAIC use-case PDF and the primary sources linked below. This is a source-availability and design assessment, not a computed profile of a particular district.

**Recommendation: build the district profile from existing legislative-district ACS estimates first. Add spatial analysis selectively for neighborhood detail and service access. Treat program eligibility and enrollment gaps as a separate evidence problem.** DBEDT already publishes House and Senate ACS profiles, so a custom geographic crosswalk is not a prerequisite for the core product. [DBEDT 2024 ACS, five-year section](https://census.hawaii.gov/acs/acs-2024/)

## The problem the PDF actually describes

The [Know Your District use case](../use-case.md), pp. 1–2, describes three connected problems: legislative offices must search scattered sources; staff manually reconcile incompatible geographies; and they separately research programs that could serve the populations they find. The resulting answers take too long, vary across offices, and seldom connect population needs to actionable outreach. The intended users are the 51 House and 25 Senate offices and government staff doing outreach or policy planning.

The desired outcome is a sourced answer to who lives in a district, what help could be relevant, and where outreach could improve uptake. Pages 3–5 require source/year/geography on every figure, disclosure of estimation and uncertainty, official program links, district maps, comparisons, a printable summary, and validation with DBEDT/READ experts. Only public aggregated data may be used; no new resident data is to be collected. Recommendations inform outreach; administering agencies determine eligibility.

There are therefore **three distinct analytical gaps**:

1. **Geographic:** translate source areas into the selected House or Senate boundary when no native district estimate exists.
2. **Population:** determine whether the data actually measures the combined group of interest, such as low-income older renters, rather than three unrelated totals.
3. **Program:** distinguish people with a relevant need, people meeting complete eligibility rules, and eligible people who are not enrolled. A map alone cannot resolve the last two gaps. Geographic overlap does not establish that the same households share each characteristic; published joint tables or an explicitly validated aggregate model are needed.

In this report, **direct district data** means the publisher provides a value for the district geography. It does **not** mean an exact count or current administrative record. ACS figures remain survey estimates. Census identifies Senate as summary level **610**, House as **620**, and Hawaiʻi as state FIPS **15**. Match chamber, district code, and boundary vintage; district number alone is ambiguous. [ACS API geography examples](https://api.census.gov/data/2024/acs/acs5/examples.html)

## Audit of sources named in the PDF

Here, **direct** means the publisher provides figures for a state House or Senate district. It does not mean an exact census count, an error-free estimate, or a household eligibility determination. **Context** means useful information whose geography cannot establish the distribution inside a district. **Overlay** means geographic features can be intersected with district boundaries, with separate rules for estimating population quantities.

| Source named in the brief | What is actually available and verified | District fit and proposed use |
|---|---|---|
| **U.S. Census Bureau / ACS** | State legislative districts are an existing ACS geography. DBEDT republishes district profile downloads; additional Census API/table coverage needs table-specific checking. | **Direct for published district tables.** This should supply the baseline, rather than estimating those same figures from tracts. See the ACS analysis below. |
| **DBEDT/READ economic and demographic data** | The State Data Center's **2024 ACS 5-year** page explicitly lists **House Districts and Senate Districts** Excel profiles. The page describes DP2 social, DP3 economic, DP4 housing and DP5 demographic sheets. DBEDT also lists tract/district interactive maps and 2022 House/Senate reference maps. [2024 ACS downloads](https://census.hawaii.gov/acs/acs-2024/), [geography products](https://census.hawaii.gov/geography/). | **Direct for the district ACS products**, with ACS sampling uncertainty. Other DBEDT products must be classified individually. These are republished Census data, not independent corroborating measurements. |
| **State of Hawaiʻi Data Book** | DBEDT explicitly describes its geographic emphasis as statewide, with more limited county and smaller-area coverage. The current landing page identifies the 2025 edition. [Data Book](https://dbedt.hawaii.gov/economic/databook/). | **Mostly context; inspect individual tables.** A table's presence in the Data Book does not establish 76-district coverage. Use for state/county comparisons and original-source discovery. |
| **DOTAX annual reports / public tax statistics** | The report catalog includes individual income statistics, tax credits and EITC. The 2023 tax-credit report's Table A-4 is grouped into **Oʻahu, Maui, Hawaiʻi and Kauaʻi tax districts**. It reports counts for renter, food/excise, dependent-care and earned-income credits. Its note says out-of-state-address N-15 credits are included in Oʻahu. [Annual catalog](https://tax.hawaii.gov/stats/a5_1annual/), [2023 tax-credit report, Table A-4](https://files.hawaii.gov/tax/stats/stats/credits/2023credit.pdf). | **No direct House/Senate observations verified in the reviewed products.** Tax district is a different geography. Valuable uptake context; cannot claim a district's unclaimed benefits by allocating county-level claims uniformly. Tax returns/claims also differ from Census households/people. |
| **DOTAX monthly collections and dashboards** | Monthly reports include GET/TAT liability “by district.” The GET report labels Oʻahu/Maui/Hawaiʻi/Kauaʻi and describes these as county data. DOTAX says dashboards aggregate its reports, which remain the official source. [Monthly catalog](https://tax.hawaii.gov/stats/a5_3txcolrpt/), [GET example and geographic footnote](https://files.hawaii.gov/tax/stats/monthly/archive/202406liab-by-d_ge_rev.pdf), [dashboard](https://tax.hawaii.gov/data-dashboard/). | **Context, not legislative district data.** Business tax activity is not a count of low-income residents or eligible households. Dashboards do not supply finer geography merely by displaying the same reports interactively. |
| **UHERO public data and reports** | UHERO describes its main Data Portal as covering the **state, four counties and external economies**, with per-series source notes. [UHERO Data](https://uhero.hawaii.edu/data/). | **Context for the portal as documented.** Useful employment, housing and economic trends. Individual research products might have finer geography; do not assume portal geography describes every UHERO report, or that public access grants redistribution rights. |
| **Bureau of Labor Statistics** | QCEW publishes industry employment/wages at county, MSA, state and national levels. This is employer-reported employment rather than a district household profile. [QCEW](https://www.bls.gov/qcew/home.htm), [access and geographic coverage](https://www.bls.gov/cew/data-overview.htm). | **Context for these regional products.** Use ACS for residents' employment/industry. Do not turn county job totals into district resident-worker totals; any finer BLS-derived layer needs its own documentation. |
| **Bureau of Economic Analysis** | BEA's regional tables distinguish state and county GDP/personal income. Its county-income definition assigns income to residence, including earnings from work elsewhere. [Personal income by county](https://www.bea.gov/data/income-saving/personal-income-by-county), [regional table catalog](https://apps.bea.gov/iTable/?ReqID=70&step=1). | **Context for the reviewed regional products.** Good county/state benchmarks; no direct state-legislative-district distribution established. A county personal-income aggregate cannot reveal how many district households meet a benefit's income rule. |
| **datatrove.ai** | Its first-party About page says it indexes metadata and points to original sources rather than hosting the data. Its source catalog labels descriptions and join keys enriched with AI. No particular district-ready measure or documented House/Senate crosswalk was verified. Retrieved via a second search route after the native reader returned an empty page. [About Datatrove](https://datatrove.ai/about), [source catalog](https://datatrove.ai/sources). | **Discovery aid / dataset-dependent; district readiness unverified.** Follow results to the source owner, check geography and licensing, and avoid double-counting copies as independent evidence. Do not promise district data merely because the brief names the service. |
| **Official district boundary files** | State GIS documents House/Senate polygons adopted in 2022, sourced from the Office of Elections. Live ArcGIS metadata confirms the vintage and numeric ID fields. A read-only query returned **51 distinct House IDs (1–51)** and **25 distinct Senate IDs (1–25)**. [House metadata](https://files.hawaii.gov/dbedt/op/gis/data/house22.pdf), [Senate metadata](https://files.hawaii.gov/dbedt/op/gis/data/senate22.pdf), [House service](https://geodata.hawaii.gov/arcgis/rest/services/AdminBnd/MapServer/33?f=pjson), [Senate service](https://geodata.hawaii.gov/arcgis/rest/services/AdminBnd/MapServer/34?f=pjson). | **Direct district geometry, not socioeconomic observations.** Use chamber + district number + boundary vintage as a key. Metadata says main Hawaiian Islands; reconcile against legal descriptions/Census geography before treating coverage as statewide, especially outlying islands. |
| **Esri / ArcGIS Living Atlas** | Esri documents ACS layers on standard Census geographies, with examples at tract level. It recommends official published estimates when the requested geography already exists, rather than approximating them by aggregation. It distinguishes free ACS layers from premium demographic content. [Living Atlas reference](https://doc.arcgis.com/en/business-analyst/web/understand-arcgis-living-atlas.htm), [demographic mapping guidance](https://www.esri.com/arcgis-blog/products/arcgis-living-atlas/mapping/best-practices-for-mapping-demographics-within-arcgis-faq). | **Overlay / table-dependent.** Useful map-ready tract/block-group layers, facility points or service areas, subject to each item's metadata and terms. Living Atlas itself is a catalog, not proof of direct district measures. Do not treat map clipping as a statistical crosswalk. |
| **Public program and eligibility information** | The brief requests a new structured inventory from administering agencies' public information; it does not identify an already complete, normalized program dataset (p. 4). | **Rules and service geography, usually not district population data.** Build an inventory linking populations to programs, official rules, geographic coverage, contacts, dates and uptake data where available. |

## Publisher-linked DBEDT district downloads

These are the exact links published under **5-Year Dataset → State Legislative Districts** on the [2024 ACS page](https://census.hawaii.gov/acs/acs-2024/):

- [2024 ACS 5-year House district profiles](https://files.hawaii.gov/dbedt/census/acs/acs2024/5yr/acs2024_5yr_house_hi.xlsx).
- [2024 ACS 5-year Senate district profiles](https://files.hawaii.gov/dbedt/census/acs/acs2024/5yr/acs2024_5yr_senate_hi.xlsx).

**Verification limit:** publisher links and the described profile coverage were verified. The browsing tool recognized the XLSX content type but could not parse it; independent download attempts received HTTP 403. Workbook headers, individual cell values and completeness were therefore **not independently inspected**. These links establish documented availability, not a completed ingestion or validated numerical profile.

## Geographic and statistical caveats that affect implementation

- **District geography and population universe are separate decisions.** Hawaiʻi's reapportionment documentation describes a permanent-resident population base and exclusions of nonpermanent military/student residents. A Census resident-population profile should not be forced to equal the reapportionment population. Retain the population definition alongside each figure. [Office of Elections reapportionment](https://elections.hawaii.gov/about-us/boards-and-commissions/reapportionment/), [2021 planning materials, p. 85](https://files.hawaii.gov/elections/files/Meeting%20Materials/Meeting-Materials-20210706.pdf).
- **House and Senate require separate joins.** An ID such as “1” is ambiguous without chamber and vintage. Do not assume that a Senate district consists of a fixed set of whole House districts; compute and validate the required spatial relationship.
- **Boundary files have coordinate systems.** State metadata distinguishes geoportal exports in WGS84 from the native UTM/NAD83 data. Reproject deliberately before intersection or area calculations. [House boundary metadata](https://files.hawaii.gov/dbedt/op/gis/data/house22.pdf).
- **Tax, Census and program units differ.** Returns, credit claims, households, families, persons and program assistance units cannot be subtracted or compared as if interchangeable. DOTAX suppression and allocation notes travel with the statistic.
- **Source-specific access limits are not proof that data do not exist.** This audit verifies publication descriptions and selected service metadata; it is not a completed inventory of every downloadable report, field or administrative aggregate.


## What can be answered directly with ACS

Use **2020–2024 ACS five-year estimates** as the baseline verified for this assessment, with matching five-year county and state comparisons. Five-year data covers small geographies; it represents a collection period, not a snapshot of October 2026. The 2024 ACS geography documentation uses 2024-session legislative boundaries. Confirm equivalence with Hawaiʻi's official plan before joining. The Census 2026 plan description reports no Hawaiʻi changes from the 2024 cycle. [Choosing ACS estimates](https://www.census.gov/programs-surveys/acs/guidance/estimates.html), [2024 geography vintage](https://www.census.gov/programs-surveys/acs/geography-acs/geography-boundaries-by-year/2024.html), [Census legislative plans](https://www.census.gov/programs-surveys/decennial-census/about/rdo/state-legislative-district.html)

The following are specific table candidates, with their 2024 five-year metadata verified. Each table still needs a district-cell completeness and reliability check during ingestion; checking the table definition is not a claim that every district cell is usable.

| Question / type of data | Direct ACS table candidates | Use and limit |
|---|---|---|
| Population and age | [B01001](https://api.census.gov/data/2024/acs/acs5/groups/B01001.html) | Children, working-age residents, 60+ or 65+ groups. Choose program-specific age bands. |
| Household situations | [B11001](https://api.census.gov/data/2024/acs/acs5/groups/B11001.html), [B11007](https://api.census.gov/data/2024/acs/acs5/groups/B11007.html) | Family/nonfamily households, living alone, older people in households. These are household measures, not lists of residents. |
| Income levels | [B19001](https://api.census.gov/data/2024/acs/acs5/groups/B19001.html), [B19013](https://api.census.gov/data/2024/acs/acs5/groups/B19013.html) | Distribution and median household income. A median cannot tell how many households satisfy a benefit cutoff. |
| Low-income children or kūpuna | [B17001](https://api.census.gov/data/2024/acs/acs5/groups/B17001.html) | Published age-by-poverty cells avoid multiplying independent age and poverty percentages. Poverty universe and program household definitions differ. |
| Employment and industries | [B23025](https://api.census.gov/data/2024/acs/acs5/groups/B23025.html), [C24030](https://api.census.gov/data/2024/acs/acs5/groups/C24030.html) | Employment status and industries of employed residents. They do not count all jobs located within the district. |
| Housing affordability | [B25070](https://api.census.gov/data/2024/acs/acs5/groups/B25070.html), [B25106](https://api.census.gov/data/2024/acs/acs5/groups/B25106.html) | Rent burden; tenure, income bands and housing-cost burden. Use the correct denominator and handle not-computed cells. |
| SNAP receipt and possible outreach need | [B22003](https://api.census.gov/data/2024/acs/acs5/groups/B22003.html), [B22010](https://api.census.gov/data/2024/acs/acs5/groups/B22010.html) | Joint poverty-by-SNAP-receipt and disability-by-SNAP-receipt cells. Receipt is self-reported over the past 12 months, not a current case count. |
| Health coverage | [B27001](https://api.census.gov/data/2024/acs/acs5/groups/B27001.html) | Uninsured population by age/sex. Insurance status alone does not establish Med-QUEST eligibility. |
| Barriers to applying | [B16004](https://api.census.gov/data/2024/acs/acs5/groups/B16004.html), [B28002](https://api.census.gov/data/2024/acs/acs5/groups/B28002.html), [B08201](https://api.census.gov/data/2024/acs/acs5/groups/B08201.html) | Language/English ability, internet subscriptions and vehicle availability can guide language support, paper applications and mobile enrollment. They do not directly measure why people have not enrolled. |

**“Kūpuna living on fixed incomes” needs an explicit definition.** Social Security receipt ([B19055](https://api.census.gov/data/2024/acs/acs5/groups/B19055.html)) does not establish that income is exclusively fixed, insufficient, or received by a person 65+. For an initial answer, report separately measured older-age poverty, older people living alone, and Social Security receipt, explaining that the combined group is unavailable unless a suitable published cross-tabulation exists.

### A concrete outreach question requiring no custom district crosswalk

Start with: **“How many households in this district are below the Census poverty threshold and report no SNAP receipt?”** The count is a published joint category, **B22003_006E**, with margin of error **B22003_006M**. This is more defensible than subtracting all SNAP households from all low-income households. It is an **outreach signal**, not a count of eligible nonparticipants. [Official B22003 variables](https://api.census.gov/data/2024/acs/acs5/groups/B22003.html)

Three qualifications matter:

- Census statistical poverty thresholds do not vary geographically; HHS eligibility guidelines have separate Hawaiʻi values. A multiple of Census poverty is not automatically the same program threshold. [Census poverty measurement](https://www.census.gov/topics/income-poverty/poverty/guidance/poverty-measures.html), [HHS guidelines](https://aspe.hhs.gov/poverty)
- SNAP applies household, income, deduction and nonfinancial rules that the ACS cell does not fully observe. Read the effective Hawaiʻi rules rather than using a generic national income cutoff. [Hawaiʻi SNAP](https://humanservices.hawaii.gov/bessd/snap/)
- Survey-reported receipt may differ from administrative enrollment. Do not label the resulting count a measured enrollment gap. Census research documents inconsistencies between survey reports and administrative participation. [Census SNAP reporting study](https://cdn.www.census.gov/library/working-papers/2017/demo/SEHSD-WP2017-03.html)

## Which additional data is useful, and what development it needs

The rows below are recommended additions within the PDF's broad demographic/program/map categories; they are not claims that the PDF supplies these particular datasets or that all have public district coverage.

| Outreach population or question | Useful evidence | Required analysis or map behavior |
|---|---|---|
| Low-income households reporting no SNAP | Native district and tract B22003; current SNAP rules; public outreach-provider locations | Direct district summary first. Overlay tract patterns to choose outreach sites; mark any tract that crosses the district. Add provider service areas and nearby providers across the boundary. |
| Older residents with limited resources | Age-by-poverty, older people living alone, disability; relevant official program rules | Use existing joint tables where possible. Overlay senior centers and application assistance only after verifying locations and service coverage. Do not infer that all older residents qualify. |
| Renters facing high housing costs | Tenure/income/cost-burden cross-tabs; current housing-program rules, income limits and application status | District measure plus tract variation; public affordable-housing locations can be point layers. Need housing-specific eligibility and availability checks. Housing need is not proof that a program is accepting applicants. [HUD Hawaiʻi resources](https://www.hud.gov/states/hawaii) |
| Families needing child care | Children by age, household structure and parents' work status; provider locations and program rules | Prefer published joint tables over multiplying totals. Provider location, service hours and capacity matter; a point on the map does not prove an available slot. Hawaiʻi CCS rules include child age, family income and parent work/school/training conditions. [Official child-care FAQ](https://childcaresubsidyapplication.dhs.hawaii.gov/FAQs/) |
| People without health coverage | Coverage by age and, where available, joint income/coverage tables; current Med-QUEST rules and assistance sites | Match rules by eligibility category; distinguish uninsured residents from likely Medicaid-eligible residents. Refer to the official pre-assessment and application. [Med-QUEST rules](https://medquest.hawaii.gov/en/resources/rules-and-policy), [official portal](https://medical.mybenefits.hawaii.gov/) |
| People facing language, internet or transport barriers | Aggregate language, internet and vehicle measures; public transit and verified application-assistance locations | Overlay service access, identify useful languages, and show offline application options. Travel time requires transport-network analysis; straight-line distance is only proximity. |
| Working households under financial pressure | ACS income and resident employment; DOTAX published credit claims; BLS/UHERO economic trends | Use tax and economic series at their actual geography. No district-specific credit nonclaimant count follows from a county/tax-district rate. A tax return is not the same unit as a household or resident. |
| Whether outreach actually increases uptake | Public aggregate applications, approvals, active cases and/or referrals, by compatible district/period/unit | Seek agency-published aggregates. If unavailable, display “district uptake unavailable.” Request publication through the challenge's prescribed channel; do not request private case records. Track campaign results only as privacy-preserving aggregates with agency partners. |

## How to handle geographic mismatch

These are proposed implementation rules, not assertions that the audited sources already provide crosswalks.

1. **Prefer a native district estimate.** Use direct district ACS for the headline and compare with the same release's county/state values. Do not replace it with a less defensible sum of interpolated tracts.
2. **Distinguish an overlay from an estimate.** Showing all intersecting tracts is useful context. A clipped polygon does not mean its original count or rate describes only the clipped portion. Preserve source boundaries or clearly mark split units.
3. **For additive counts, weight by the relevant population.** For source area `s` and district `d`, estimate `count(d) = sum(count(s) * weight(s,d))`. Derive weights from the smallest suitable public population or housing-unit support, ideally blocks, and record the reference year. Use household/housing weights for household measures when suitable; total population is not always an appropriate denominator. Whole-block equivalency files can have split-block limitations. [Census block-equivalency guidance](https://www.census.gov/programs-surveys/decennial-census/about/rdo/state-legislative-district.2024.html)
4. **Recalculate rates from allocated numerators and denominators.** Do not average tract percentages or medians. Medians and quantiles require a distribution or a separate model. Population weighting still assumes how the characteristic is distributed inside split areas; it does not recover observations.
5. **Do not turn county trends into observed district figures.** A county total scaled by district population is a modeling assumption. In the first version, show it as county context. County-only data cannot reveal within-county differences, regardless of map detail.
6. **Treat ZIPs carefully.** USPS delivery ZIPs and Census ZCTAs are different objects. Confirm the source's actual geography before using a ZCTA boundary or crosswalk. Do not join them merely because their codes look alike. [Census ZCTA definition](https://www.census.gov/programs-surveys/geography/guidance/geo-areas/zctas.html)
7. **Use analysis-grade boundaries for calculations.** Retain the official full-resolution geometry and vintage; use simplified geometry only for display. Process House and Senate separately; verify any claimed nesting rather than assuming it.
8. **Carry two kinds of uncertainty.** Preserve ACS sampling margins of error and separately disclose geographic allocation/model uncertainty. A survey margin of error does not include uncertainty introduced by a custom spatial allocation. Derived statistics need appropriate variance calculations; selected tables have variance replicates. [ACS accuracy guidance](https://www2.census.gov/programs-surveys/acs/tech_docs/accuracy/ACS_Accuracy_of_Data_2024.pdf), [variance tables](https://www.census.gov/programs-surveys/acs/data/variance-tables.2024.html)

### What the district leader should see

After selecting a chamber and district, show a short profile and a few actionable outreach opportunities. Each opportunity should explain **the population signal, relevant program, evidence strength, enrollment evidence if any, and a concrete next action** with an official link.

The map should offer district outlines, one selected indicator at a time, optional tract/block-group source boundaries, and verified assistance/provider locations and service areas. Show nearby services across district lines. In a split tract's detail panel, identify the full-tract statistic and any separately calculated allocated contribution. Use a visible label on every figure: **Published for district**, **Estimated from smaller areas**, or **County/state context**. A separate label should describe program evidence: **Relevant need**, **Modeled eligibility**, or **Comparable enrollment data available**. Do not add overlapping outreach populations as if they were distinct residents.

Provide the same information in an accessible table and printable one-page brief, including source, collection period, geography, method, uncertainty and last program-rule check. Avoid presenting an arbitrary composite score as an eligibility or under-enrollment rate. These UX recommendations implement the PDF's transparency and accessibility requirements rather than adding precision the data lacks.

## A practical delivery sequence

| Stage | Concrete deliverable | Evidence needed to move on |
|---|---|---|
| 1. Establish the data contract | A source registry and 76-district catalog. Fields: publisher, table/variable, unit/universe, collection period, release, chamber/GEOID, boundary vintage, estimate/MOE/status, transformation, source URL, retrieval date, license. | Confirm district codes and boundary compatibility; keep unknown/suppressed distinct from zero. Document differences between resident population and any adjusted reapportionment base. |
| 2. Deliver useful district profiles | Ingest DBEDT district workbooks or Census district tables; publish about 15–20 core measures for House and Senate, same-release comparisons, citations and print export. | Cross-check representative urban/rural and small-population districts against official tables; check coverage of all 51 House and 25 Senate districts. Do not add House and Senate populations together. |
| 3. Connect three program families | A reviewed, versioned registry for SNAP, Med-QUEST and Child Care Subsidy. Store administering agency, jurisdiction, eligibility category, income definition/period, household unit, age/disability/work criteria, exclusions, effective dates, availability, contacts and official application URL. | Have program experts review mappings. Include clear rejection/unknown cases. Use a rule engine or explicit mappings, with the language model explaining retrieved evidence rather than calculating unsupported eligibility. |
| 4. Demonstrate one outreach opportunity | Begin with district B22003 below-poverty/no-SNAP-receipt estimates and a verified local SNAP outreach provider. Add a tract overlay showing where an outreach event may be useful. | Validate the source cells and MOEs, explain proxy limitations, verify the provider serves the area, and obtain staff feedback on the proposed action. No invented number of eligible nonparticipants. |
| 5. Add spatial estimation only where it earns its cost | A reusable crosswalk pipeline for selected non-native measures, plus a method panel and accessible overlay controls. | Check weight conservation within each chamber, split units, coastline/water artifacts and sensitivity to weighting choices. Compare reconstructed ACS totals against native district estimates as a diagnostic, not an expectation of equality. |
| 6. Establish uptake evidence and maintenance | An agency-reviewed way to compare need and aggregate uptake, plus program-rule refreshes and stale-data alerts. | Align population universe, geography, time period and unit before calculating any gap. Measure validated referrals/applications/approvals where possible; describe attribution limits. If uptake data remains unavailable, keep the product an outreach-prioritization tool. |

This sequence fits the existing FastAPI/SQLite/Jinja/htmx/Leaflet direction recorded in `AGENTS.md`: precompute trusted figures and map layers, store provenance with each value, and let chat retrieve and explain them. It does not require changing the stack or building a general-purpose spatial estimation engine before delivering value.

## Verification limits and next research questions

- **Source audit, not a downloaded district dataset:** the publisher explicitly lists the House/Senate workbooks; their contents were not parsed in this run because file retrieval was blocked. The Census metadata endpoints worked, but live data queries without a key redirected to an HTML “Missing Key” page. A successful HTTP status is not proof that data was retrieved. [Current Census API instructions](https://api.census.gov/data/2024/acs/acs5/examples.html)
- Public alternatives include the district workbooks and Census downloadable summary files. Confirm parsing, completeness and available MOEs before committing to either ingestion path. [ACS table-based summary files](https://www.census.gov/programs-surveys/acs/data/summary-file.2024.html)
- The audit establishes the geography of the cited products; it does not prove that no other product from the same institution has district-level data. Datatrove's specific district-ready source coverage and reuse terms remain unresolved; the existence of its discovery catalog is verified.
- The first subject-matter questions are which indicators READ prioritizes, which agencies can publish comparable district participation aggregates, and who will maintain program rules. The PDF directs challenge questions to Slack `#c_dbedt_agent`; this report does not contact anyone.


## Retrieval coverage

The source classifications are supported by primary publication descriptions, table metadata and selected live GIS queries. Numeric district cells and some file downloads remain unvalidated. Native search and a second search route recovered first-party evidence where direct retrieval was blocked; webfetch tiers 0, 1 and 2 did not retrieve the challenged DBEDT page.

```json
{
  "web_context": {
    "profile": {
      "agent": "codex",
      "unavailable": [
        "local.reddit_cookie: blocked"
      ]
    },
    "status": "partial",
    "tried": [
      {
        "route": "native search",
        "host": "census.gov",
        "result": "ok"
      },
      {
        "route": "native search",
        "host": "humanservices.hawaii.gov",
        "result": "ok"
      },
      {
        "route": "urllib Census data query",
        "host": "api.census.gov",
        "result": "blocked",
        "detail": "Redirected to HTML Missing Key page; no numerical records retrieved"
      },
      {
        "route": "native search",
        "host": "census.hawaii.gov",
        "result": "ok"
      },
      {
        "route": "webfetch tier 0",
        "host": "census.hawaii.gov",
        "result": "challenge"
      },
      {
        "route": "webfetch tier 1",
        "host": "census.hawaii.gov",
        "result": "challenge"
      },
      {
        "route": "webfetch tier 2",
        "host": "census.hawaii.gov",
        "result": "blocked"
      },
      {
        "route": "native search",
        "host": "files.hawaii.gov",
        "result": "ok",
        "detail": "Selected indexed reports available; district workbook fetches blocked"
      },
      {
        "route": "native retrieval XLSX",
        "host": "files.hawaii.gov",
        "result": "blocked"
      },
      {
        "route": "native search",
        "host": "tax.hawaii.gov",
        "result": "ok",
        "detail": "Publisher report catalog/search evidence; some open attempts 403"
      },
      {
        "route": "native search",
        "host": "dbedt.hawaii.gov",
        "result": "ok",
        "detail": "Publisher descriptions; some open attempts 403"
      },
      {
        "route": "native retrieval",
        "host": "uhero.hawaii.edu",
        "result": "ok"
      },
      {
        "route": "native retrieval",
        "host": "bls.gov",
        "result": "ok"
      },
      {
        "route": "native retrieval",
        "host": "bea.gov",
        "result": "ok"
      },
      {
        "route": "native retrieval",
        "host": "datatrove.ai",
        "result": "empty"
      },
      {
        "route": "ketch search",
        "host": "datatrove.ai",
        "result": "ok"
      },
      {
        "route": "native retrieval",
        "host": "datatrove.ai",
        "result": "refused",
        "detail": "About/catalog unavailable through native reader; ketch returned first-party text"
      },
      {
        "route": "urllib ACS metadata",
        "host": "api.census.gov",
        "result": "ok",
        "detail": "17 cited table definition pages checked for HTTP 200 and metadata content"
      },
      {
        "route": "native retrieval",
        "host": "medquest.hawaii.gov",
        "result": "ok"
      },
      {
        "route": "native retrieval",
        "host": "childcaresubsidyapplication.dhs.hawaii.gov",
        "result": "ok"
      }
    ],
    "sources": [
      {
        "url": "https://census.hawaii.gov/acs/acs-2024/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/examples.html",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://census.hawaii.gov/geography/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://dbedt.hawaii.gov/economic/databook/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://tax.hawaii.gov/stats/a5_1annual/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://files.hawaii.gov/tax/stats/stats/credits/2023credit.pdf",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://tax.hawaii.gov/stats/a5_3txcolrpt/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://files.hawaii.gov/tax/stats/monthly/archive/202406liab-by-d_ge_rev.pdf",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://tax.hawaii.gov/data-dashboard/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://uhero.hawaii.edu/data/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.bls.gov/qcew/home.htm",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.bls.gov/cew/data-overview.htm",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.bea.gov/data/income-saving/personal-income-by-county",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://apps.bea.gov/iTable/?ReqID=70&step=1",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://datatrove.ai/about",
        "route": "ketch search (first-party indexed text)"
      },
      {
        "url": "https://datatrove.ai/sources",
        "route": "ketch search (first-party indexed text)"
      },
      {
        "url": "https://files.hawaii.gov/dbedt/op/gis/data/house22.pdf",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://files.hawaii.gov/dbedt/op/gis/data/senate22.pdf",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://geodata.hawaii.gov/arcgis/rest/services/AdminBnd/MapServer/33?f=pjson",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://geodata.hawaii.gov/arcgis/rest/services/AdminBnd/MapServer/34?f=pjson",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://doc.arcgis.com/en/business-analyst/web/understand-arcgis-living-atlas.htm",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.esri.com/arcgis-blog/products/arcgis-living-atlas/mapping/best-practices-for-mapping-demographics-within-arcgis-faq",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://files.hawaii.gov/dbedt/census/acs/acs2024/5yr/acs2024_5yr_house_hi.xlsx",
        "route": "publisher link via native search; file download blocked"
      },
      {
        "url": "https://files.hawaii.gov/dbedt/census/acs/acs2024/5yr/acs2024_5yr_senate_hi.xlsx",
        "route": "publisher link via native search; file download blocked"
      },
      {
        "url": "https://elections.hawaii.gov/about-us/boards-and-commissions/reapportionment/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://files.hawaii.gov/elections/files/Meeting%20Materials/Meeting-Materials-20210706.pdf",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.census.gov/programs-surveys/acs/guidance/estimates.html",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.census.gov/programs-surveys/acs/geography-acs/geography-boundaries-by-year/2024.html",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.census.gov/programs-surveys/decennial-census/about/rdo/state-legislative-district.html",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B01001.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B11001.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B11007.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B19001.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B19013.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B17001.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B23025.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/C24030.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B25070.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B25106.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B22003.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B22010.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B27001.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B16004.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B28002.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B08201.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://api.census.gov/data/2024/acs/acs5/groups/B19055.html",
        "route": "urllib ACS metadata"
      },
      {
        "url": "https://www.census.gov/topics/income-poverty/poverty/guidance/poverty-measures.html",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://aspe.hhs.gov/poverty",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://humanservices.hawaii.gov/bessd/snap/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://cdn.www.census.gov/library/working-papers/2017/demo/SEHSD-WP2017-03.html",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.hud.gov/states/hawaii",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://childcaresubsidyapplication.dhs.hawaii.gov/FAQs/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://medquest.hawaii.gov/en/resources/rules-and-policy",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://medical.mybenefits.hawaii.gov/",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.census.gov/programs-surveys/decennial-census/about/rdo/state-legislative-district.2024.html",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.census.gov/programs-surveys/geography/guidance/geo-areas/zctas.html",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www2.census.gov/programs-surveys/acs/tech_docs/accuracy/ACS_Accuracy_of_Data_2024.pdf",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.census.gov/programs-surveys/acs/data/variance-tables.2024.html",
        "route": "native search / primary-source retrieval"
      },
      {
        "url": "https://www.census.gov/programs-surveys/acs/data/summary-file.2024.html",
        "route": "native search / primary-source retrieval"
      }
    ]
  }
}
```
