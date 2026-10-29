# District data and benefit outreach: agent build guide

> Copied into the product repo on 2026-10-29 from the team's planning notes (not public). Research guidance: where it disagrees with `AGENTS.md` or `docs/data.md`, those win. `AGENTS.md` is code-owned, so propose a decision in the PR and the Code Owner records it. Dated facts stay dated: recheck current official rules before shipping a referral.

Prepared 2026-10-29 from the district-source investigation. Audience: agents planning, implementing or reviewing the HAIC Know Your District application.

**Build a sourced district profile first, connect it to reviewed program information, then add spatial analysis where it answers a specific outreach question.** The main risk is treating a plausible population estimate as proof of eligibility or under-enrollment.

## Read first

Read this guide before changing data ingestion, population measures, program matching, geographic analysis, chat claims or evaluation. Then follow the relevant branch below; the detailed source inventory stays in the research audit.

| Authority / reference | Use |
|---|---|
| [Use case](../use-case.md) (compact copy of the official PDF), pp. 1–5 | Requirements and constraints; outranks this guide. |
| [AGENTS.md](../../AGENTS.md) | Adopted stack, operations and release rules; outranks recommendations here. |
| [Source audit](../research/district-data-source-audit.md#audit-of-sources-named-in-the-pdf) | Authority for this investigation's source classifications, citations and verification limits. Read when selecting or replacing a source. |
| [ACS measure inventory](../research/district-data-source-audit.md#what-can-be-answered-directly-with-acs) | Candidate tables and interpretation limits. Read when defining a measure or population. |
| [Geographic methods](../research/district-data-source-audit.md#how-to-handle-geographic-mismatch) | Crosswalk methods and statistical caveats. Read before allocating any source-area value. |
| [AGENTS.md](../../AGENTS.md) | Product rules, stack, layout and tests; engineering principles in [docs/engineering.md](../engineering.md). |
| [Benefit outreach guide](benefit-outreach.md) | Read when choosing a program/demo population, checking recent expansions or access barriers, or creating program-outreach tasks. Follow its dossier links for findings and source limits. |

This guide owns the execution sequence and completion criteria. The audit owns the detailed findings; update that evidence when new research changes a classification. The sequence below is recommended implementation guidance, not a claim that the application already implements it. Inspect the actual code and tracker before creating work.

## Findings that should change the build

1. **Native district data exists.** Census ACS publishes state legislative district estimates, and DBEDT lists separate House and Senate five-year profile workbooks. Core population, income, employment, housing and household summaries can start there. A general tract-to-district estimation engine is not a prerequisite.
2. **Availability has not become validated data yet.** The investigation verified publication descriptions and table definitions, not workbook cells. Downloads were blocked; keyless Census data requests returned an HTML “Missing Key” page. Treat retrieval and ingestion as unfinished work, even when HTTP status is 200.
3. **Classify products, not agencies.** DBEDT has direct district ACS products and broader Data Book tables. Reviewed DOTAX, UHERO portal, BLS and BEA products provide broader context. DOTAX “district” refers to tax geography. Living Atlas and Datatrove require item-level checks. Republishing Census data does not create an independent measurement.
4. **There are three separate evidence problems.** Geographic alignment asks whether a value describes this district. Population alignment asks whether published data measures the combined group being discussed. Program alignment asks whether that group meets eligibility rules and whether eligible members are enrolled. A spatial intersection resolves neither household intersections nor eligibility by itself.
5. **A useful initial outreach signal already has a joint table.** ACS B22003 measures poverty status together with reported SNAP receipt. It supports an evidence-backed outreach example without manufacturing the intersection from separate totals. Its interpretation and release gate are specified below.

All five findings are supported and qualified in the [source audit](../research/district-data-source-audit.md). The investigated baseline is **2020–2024 ACS five-year data**, not a current-year administrative census. Recheck release and program-rule dates when implementing.

## Product outcome and scope

The PDF's problem is slow, inconsistent manual work across scattered sources and incompatible geographies, followed by disconnected program research. The product should help one legislative office answer:

> Who lives in my district, which existing programs are relevant, and what outreach action does the evidence support?

Keep the three outputs connected: a district profile, a program opportunity with its reasoning and official next step, and a map or printable brief that preserves the evidence. Program eligibility is determined by administering agencies. The application describes populations using public aggregates; it collects no new resident records.

Treat these as different product claims:

| Claim | Evidence required |
|---|---|
| A population has a relevant need | A measure with a defined universe, period, geography and uncertainty, plus a reviewed connection to a program. |
| A population is likely eligible | An explicit aggregate estimation method using the program's applicable rules, with unobserved conditions, assumptions and validation disclosed. |
| Eligible residents are not enrolled | A defensible eligible-population estimate and comparable participation evidence, including overlap and coverage assumptions. |
| An outreach action increased uptake | Comparable aggregate outcome observations and an evaluation design that states attribution limits. |

Label the supported claim. When the stronger claim lacks evidence, return the weaker supported claim and identify the missing input. That is useful partial coverage of the brief; it does not complete the missing analysis.

## Execution sequence

Each step ends with evidence another agent can inspect. Record task status in the existing tracker and keep research decisions in the repository.

### 1. Inspect and establish the data path

Inspect existing ingestion, stored measures, geography files, program records, citations and tests. Map existing behavior to the stages here so completed work is reused. Retrieve a small real district sample through an authorized API path or official downloadable product; validate response format and content before parsing. Use the audit's [publisher-linked downloads](../research/district-data-source-audit.md#publisher-linked-dbedt-district-downloads) and Census alternatives.

**Done when:** a reproducible retrieval produces parseable data for at least one House and one Senate district, retains source identifiers and uncertainty/status fields, and documents the chosen access path. A blocked source has a recorded failure and bounded next attempt or alternative. Listing a URL is not this milestone.

### 2. Establish district identity and a complete baseline

Use chamber, official district identifier and boundary vintage as identity. Reconcile State GIS geometry with the Census statistical geography. Then ingest the agreed core measure set for every district, with matching-period county/state benchmarks. Begin with the audit's ACS inventory; record READ's requested priorities when available.

**Done when:** all 51 House and 25 Senate districts appear in a coverage manifest; every selected measure has a value or explicit missing/status reason; boundary compatibility is documented; and independent source checks cover representative urban, rural and small-population cases in both chambers. Missing cells remain visible rather than becoming zeros.

### 3. Deliver one complete outreach example

Implement the SNAP example below from validated source cells through deterministic calculation, cited chat answer, district card, official program referral and print export. It can proceed before a full neighborhood estimation pipeline.

**Done when:** all four surfaces show the same district, period, units, estimate, uncertainty and interpretation; an evaluator can trace the displayed figure to the source cells; and the referral links to current official information. A narrative drafted around placeholder numbers does not pass.

### 4. Broaden the reviewed program inventory

The recommended first program families are SNAP, Med-QUEST and Child Care Subsidy. These are research priorities, not a READ-approved final scope. Store rules and evidence as structured records; review distinct eligibility categories separately. The registry contract is below.

**Done when:** each included program has a dated official rule source, explicit mapping from supported population signals, documented unknown conditions, application/contact information and a refresh owner or mechanism. Tests include relevant, irrelevant and insufficient-evidence cases. Expert review remains explicitly pending until it occurs.

### 5. Add a map layer that changes an outreach decision

Choose a question such as where to hold application assistance. Start with source-area indicators and verified assistance locations/service areas. Implement allocation only if an unanswered district question requires it and no suitable native district measure exists.

**Done when:** the map's source areas, split units, methods and limitations are inspectable; nearby services across district lines are represented where relevant; and the accessible table communicates the same findings. Any allocated result passes the geographic checks below before publication.

### 6. Validate outcomes and release coverage

Investigate district uptake data while earlier steps proceed. Use public aggregates that can be compared legitimately. Assemble the acceptance evidence below and obtain the PDF's requested subject-matter and user validation when available.

**Done when:** the release identifies implemented capabilities, unresolved evidence gaps, machine validation results and human review status separately. An enrollment-gap claim appears only after its comparability gate passes. Continue useful profile and referral work while participation data is unavailable.

## First outreach example: poverty and no reported SNAP

Use ACS table **B22003**:

- `B22003_006E`: estimated households below the Census poverty level that did not report SNAP receipt in the past 12 months.
- `B22003_006M`: the corresponding published margin of error.
- Geography: the selected native legislative district; baseline release: ACS 2024 five-year, covering 2020–2024.

Verify these definitions and usable district cells at ingestion. If adding a percentage, define its household denominator and propagate uncertainty appropriately. The official variable metadata and interpretation cautions are linked in the [audit's concrete outreach example](../research/district-data-source-audit.md#a-concrete-outreach-question-requiring-no-custom-district-crosswalk).

**Supported answer:** an estimated number of households meeting that survey-defined condition, followed by an explanation that SNAP outreach may be useful and an official referral. The source question concerns reported receipt during a past period; it does not establish present enrollment or eligibility.

**Release gate:** independently reproduce the selected value and MOE; preserve the survey definition in every surface; check current Hawaiʻi SNAP rules; and verify any assistance provider's service area and contact. Provider presence, open appointments and capacity are separate facts.

The initial example becomes stronger through an agency-reviewed aggregate eligibility model and comparable uptake data. Until then, use the outreach-signal claim defined above.

## Prioritized lines of inquiry

Priorities reflect dependency and information value. Technical discovery can proceed autonomously. Questions requiring agency knowledge or product judgment should be recorded as an open question on the Issue or PR, blocking only dependent claims or features. This guide authorizes no external messages; prepare questions for the PDF's designated `#c_dbedt_agent` channel for an authorized person to send.

| Priority / suggested owner | Inquiry and bounded next action | Completion evidence / consequence |
|---|---|---|
| **P0 · data** | Can the official district workbooks or Census products supply the chosen measures and MOEs reproducibly? Parse a real sample, inspect headers, annotations and geography coverage; compare supported access paths. | A selected ingestion path, real sample and coverage manifest. This gates numerical profiles; a second retrieval failure should change the attempt or source, not repeat indefinitely. |
| **P0 · GIS/data** | Are State GIS and Census districts equivalent for the selected release? Check vintage, identifiers, coordinate system, split boundaries and outlying-island coverage. | A documented join and discrepancy disposition. Resolve mapping identity before publishing an overlay as district evidence. |
| **P0 · program/data** | Which exact eligibility conditions can public aggregates observe? Compare SNAP rules with the available joint tables; list missing household, income-period and nonfinancial conditions. | A rule-to-variable mapping and explicit claim ceiling. It determines whether the feature can support relevance, modeled eligibility or neither. |
| **P1 · agency liaison/data** | Are comparable public participation aggregates available? Search administering-agency publications; prepare a request specifying program, geography, period, unit, privacy/suppression and count definition. | An accessible aggregate dataset plus comparability assessment, or a documented availability gap. County figures remain context. This gates measured district under-enrollment, not profile delivery. |
| **P1 · product/READ liaison** | Which profile indicators and outreach decisions matter most to a district office? Present the short core inventory and SNAP example for review; ask what action the answer would change. | Ranked indicators and a concrete outreach use case. Use provisional choices while feedback is pending and label approval status accurately. |
| **P1 · UX/program** | Which verified assistance locations actually serve the population? Check service areas, languages, application channels, hours and available capacity information. | A usable referral and a map layer that helps choose an action. Unknown capacity remains unknown. |
| **P1 · evaluation** | Which claims are stable enough to publish? Inspect MOE, sparse cells, suppression, denominators and cross-surface agreement; test ambiguous requests such as “fixed income.” | A reliability policy with rationale and adversarial examples. Broad survey uncertainty should narrow the answer, not disappear in prose. |
| **P2 · GIS/statistics** | What specific question remains after native district data and overlays? Select one measure, then compare feasible allocation methods and sensitivity. | A method justified by that question and validated on diagnostic cases. This determines whether a crosswalk pipeline earns its cost. |
| **P2 · source research** | Do individual UHERO, Living Atlas, Datatrove or other named-source products add unique district-relevant evidence? Inspect source owner, geography, period, license and refresh path for one candidate at a time. | A documented addition or rejection. Extra catalogs and republished copies do not count as new coverage. |
| **P2 · maintenance** | Who maintains program rules, source freshness and successful retrieval? Identify effective dates, change checks and review ownership. | A reproducible refresh with stale/failed states visible. An undated successful demo is insufficient for maintenance readiness. |

## Data and claim contracts

Adapt these semantic requirements to existing models rather than creating parallel schemas. Keep field definitions in the implementation's canonical contract once adopted; this guide describes what that contract must preserve.

### Measures and provenance

Every displayed value must retain:

| Group | Required meaning |
|---|---|
| Identity | Publisher and product; table/variable; release; chamber/GEOID when applicable; boundary vintage. |
| Population | Unit, universe and exclusions; numerator/denominator definitions; residence versus workplace where relevant. |
| Time | Collection/reference period, income-dollar basis when relevant, release and retrieval dates. |
| Value | Estimate, applicable margin of error and confidence level, source annotation and missing/suppression status. |
| Transformation | Native geography; target geography; direct, allocated, modeled or contextual treatment; reproducible method and inputs. |
| Evidence | Official source URL and locator, preserved input/version, validation result and use/redistribution terms. |

Preserve each source's population definition. Census resident totals and Hawaiʻi's adjusted reapportionment base need not agree. Returns, credit claims, people, households and program assistance units remain distinct. Compare districts with the same product/period/universe; identify all relevant counties when a district crosses county boundaries.

Track **documented**, **retrieved**, **parsed** and **validated** evidence separately. A publisher link proves documented availability; content-checked bytes prove retrieval; parsed cells prove extraction; independent checks establish the validation performed. The release selects supported claims from that evidence rather than presenting an undifferentiated “verified” flag.

### Programs and opportunity mappings

Each program record should preserve administering agency, jurisdiction/service area, official rule and application URLs, eligibility category, household/assistance-unit definition, income basis and period, age/disability/work and other relevant conditions, exceptions, effective dates, availability status, contact, last check and refresh responsibility.

Each population-to-program mapping should reference the signal's measure IDs, explain relevance, list observed and unobserved conditions, state the supported claim and retain review status. Income-only screening is a proxy when the full rule set is unobserved. Apply Hawaiʻi-specific guidelines where required; Census poverty thresholds, program poverty guidelines, state median income and area median income are different standards.

### Geography and allocation

Use the [audit's geographic methods](../research/district-data-source-audit.md#how-to-handle-geographic-mismatch) for the method itself. The implementation must preserve these boundaries between claims:

- A native district estimate supplies the headline when available. Source-area overlays explain local variation.
- A clipped tract retains its full-tract statistic unless a separate allocation is explicitly calculated and labeled.
- Count allocation uses weights appropriate to the measured universe. Rates are recomputed from compatible numerators and denominators; medians need distributions or another justified method.
- Full-resolution official geometry supports analysis; simplified files support display. House and Senate are processed independently; cross-chamber totals would double-count residents.
- Survey uncertainty and allocation/model uncertainty are recorded separately. ZIP delivery codes require a documented relationship to any ZCTA geometry used.

### Participation comparability

Before publishing an enrollment gap, record a comparability assessment covering geography/vintage, period, units, eligibility definition, assistance-unit definition, enrollment/receipt definition and coverage. Establish which participants overlap the estimated eligible population; subtracting incompatible totals cannot establish nonparticipation. Distinguish applications, approvals, active cases, annual recipients and point-in-time enrollment.

If these conditions fail, the output is an outreach signal or contextual comparison with the mismatch stated. Public aggregate participation data is the research target; private case records are outside the PDF's scope.

## Chat, map and print behavior

Chat selects relevant validated records and explains their meaning. Calculations and rule mappings live in inspectable application logic. Preserve numeric lineage through chat responses, district cards, map panels and print exports. Questions involving unsupported combinations should return available joint measures or explain the missing evidence.

For the PDF's “kūpuna on fixed incomes” example, first establish what “fixed income” means and whether a published joint table measures that group. Social Security receipt alone is neither exclusive fixed income nor an age/poverty intersection. Offer measured alternatives, such as older-age poverty or older people living alone, with their actual definitions.

Use visible geography labels: **Published for district**, **Estimated for district**, **County/state context**. Place the supported program claim beside the opportunity. Show source period and uncertainty where a leader evaluates the figure, with detail available in one step. A missing measure should identify the missing evidence and leave supported measures usable.

The map should offer one interpretable indicator at a time, source boundaries/split-unit details and relevant assistance locations/service areas. Geographic co-location is an outreach hypothesis, not proof of a household-level combination. Proximity and measured travel time have different labels. Overlapping population groups remain overlapping when summarized.

Provide equivalent tables, plain-language explanations and printable sources. Apply the PDF's WCAG 2.1 AA, nonpartisanship and correct ʻokina/kahakō requirements through the product rules in [AGENTS.md](../../AGENTS.md) and [docs/plain-language.md](../plain-language.md). Consult [AGENTS.md](../../AGENTS.md) for the selected map and print implementation; this research does not require a stack change.

## Acceptance evidence for reviewers

Use the repository's actual test commands and fixtures. Tests should detect wrong conclusions, not merely mirror implementation details. Attach the relevant evidence to each task's completion record.

| Area | Evidence to inspect |
|---|---|
| Retrieval | Real response-format validation; blocked HTML/missing-key handling; selected source path and source version. |
| Coverage | 51 House and 25 Senate identities; per-measure usable/missing status; explicit handling of any non-district geography records. |
| Numeric accuracy | Independent reproduction from official cells, including B22003 estimate/MOE and any derived denominator; source annotations preserved. |
| Geography | Vintage/join verification; split-unit cases; appropriate projection; analysis/display separation; allocation conservation and sensitivity when allocation exists. |
| Population reasoning | Joint-table checks; incompatible-unit cases; fixed-income ambiguity; sparse/suppressed cells and overlapping groups. |
| Program reasoning | Effective rule versions; observed/unknown criteria; relevant, irrelevant and insufficient-evidence examples; official referral validity. |
| Claims across surfaces | Same measure identity, values, units, period, uncertainty and interpretation in chat/card/map/print; inspectable citations. |
| Accessibility and usability | Keyboard/screen-reader access, equivalent tables, legible uncertainty and usable print; staff feedback on a concrete outreach action. |
| Validation status | Automated results, DBEDT/READ review, program review and user feedback recorded separately with open gaps. |

The PDF's success scenario includes expert-checked figures and relevant recommendations, plus at least one population/program combination where outreach could measurably improve uptake. The SNAP example is a candidate for that demonstration, not evidence that impact has already occurred. The release report must distinguish a demonstrated workflow from measured enrollment improvement.

## Handoff and document maintenance

For each completed investigation, leave the question answered, primary evidence and retrieval date, extraction/validation status, operational consequence, remaining uncertainty and the specific next action. Update the source audit when source facts change; update this guide when the build sequence or claim requirements change. Record adopted product decisions in [AGENTS.md](../../AGENTS.md) rather than silently promoting a research recommendation.
