# Benefit outreach: program priorities and research guidance

> Copied into the product repo on 2026-10-29 from the team's planning notes (not public). Research guidance: where it disagrees with `AGENTS.md` or `docs/data.md`, those win. `AGENTS.md` is code-owned, so propose a decision in the PR and the Code Owner records it. Dated facts stay dated: recheck current official rules before shipping a referral.

Research snapshot: **2026-10-29**. Read before selecting program/demo populations, implementing recommendation rules, or creating program-outreach tasks.

**Connect a district population to an existing program and a useful staff action.** The strongest opportunities found were EITC, Preschool Open Doors, Hawaiʻi ABLE and WIC. Their evidence supports different claims; selecting a compelling story does not establish district eligibility or under-enrollment.

The [use case](../use-case.md) and [AGENTS.md](../../AGENTS.md) govern scope. This is research guidance, not an adopted program-scope decision. Inspect the actual implementation and tracker before creating work. The product remains read-only and uses public aggregate data.

## Read by task

| Task | Reference |
|---|---|
| Choose a program or use an underuse claim | The relevant dossier in the [benefit-program evidence report](../research/benefit-program-access.md#program-dossiers); it owns findings, dates, sources and limitations. |
| Define or count the district audience | [District-data build guide](district-data-build-guide.md#data-and-claim-contracts), then the [source audit's measure inventory](../research/district-data-source-audit.md#what-can-be-answered-directly-with-acs). These own statistical/geographic rules and source availability. |
| Create tasks | [Inquiry queue](#inquiry-queue). |
| Review a recommendation | [Program validation cases](#program-validation-cases), plus the district-data guide's [acceptance evidence](district-data-build-guide.md#acceptance-evidence-for-reviewers). |

## Priorities

These are inquiry priorities based on relevance and evidence, not a requirement to expand the demo catalog. The district-data guide's initial SNAP example remains a useful candidate. Resolve data feasibility before committing to any alternative.

| Priority | Program | Finding the team must see | First inquiry |
|---|---|---|---|
| **P0** | [Federal/Hawaiʻi EITC](../research/benefit-program-access.md#eitc) | A quantified historical Hawaiʻi federal-credit participation gap, followed by a larger refundable state credit. | Can a defensible district audience be described while preserving federal/state claim and tax-unit distinctions? |
| **P0** | [Preschool Open Doors](../research/benefit-program-access.md#preschool-open-doors) | Recent expansions coexist with historical underspending, application delays and provider/work-schedule constraints. | Which families can use the current subsidy, and what prevents approval from becoming attendance? |
| **P0** | [Hawaiʻi ABLE](../research/benefit-program-access.md#hawaii-able) | The Legislature explicitly identified underuse associated with unfamiliarity/fear; federal eligibility expanded in 2026. | How should outreach reach newly eligible adults when disability-onset criteria are absent from district aggregates? |
| **P1** | [WIC](../research/benefit-program-access.md#wic) | National participation falls across early-childhood ages; redemption can fail after enrollment. | Can Hawaiʻi age-specific retention and redemption evidence support local targeting? |
| **P1** | [SNAP / COFA](../research/benefit-program-access.md#snap-and-cofa) | Interview-access accounts and restored eligibility create distinct navigation and re-outreach needs. | Can staff connect a district need signal with verified local application assistance under current rules? |
| **P1** | [Medicare cost assistance](../research/benefit-program-access.md#medicare-cost-assistance) | Expanded Extra Help and historical national under-enrollment warrant investigation. | Which Hawaiʻi rules, automatic-eligibility routes and local assistance apply? |
| **P1** | [DA BUX](../research/benefit-program-access.md#da-bux) | SNAP households can miss a separate produce incentive through unfamiliarity or retailer access. | Which participating retailers and access procedures currently serve the district? |
| **P2** | [Follow-up candidates](../research/benefit-program-access.md#follow-up-candidates) | SUN Bucks, energy assistance and child wellness incentives have strong household matches but weaker verified local underuse evidence. | Establish current availability and local uptake before promoting them as measured gaps. |

The [expired HEFAP case](../research/benefit-program-access.md#expired-hefap) demonstrates awarded assistance going unused. Keep it historical; use the mechanism to investigate current redemption and expiration communications.

## Workflow for program work

1. **Choose the claim.** Read the dossier and the district-data guide's claim definitions. Identify whether the task concerns a relevant audience, modeled eligibility, comparable nonparticipation, unused issued benefits or constrained service capacity. **Done when:** the proposed output names the claim and the evidence needed to support it.
2. **Verify the period.** Retrieve current official rules, application availability and assistance routes. Distinguish enactment, effective date and actual implementation; keep historical statistics dated. **Done when:** every operational field has a checked official source or an explicit unresolved status that limits the recommendation.
3. **Join evidence to action.** Use validated population measures under the existing district-data contracts. Identify the observed barrier and a feasible staff action: targeted information, a navigator referral, an outreach-planning lead or an agency follow-up. **Done when:** the audience, program, reason for attention, unknown eligibility conditions and verified next step can be inspected together.
4. **Deliver one complete example.** Follow the district-data guide's cross-surface acceptance process and the cases below. **Done when:** chat, card, map/table and print preserve the same evidence and limitations; machine validation and program-expert review status are recorded separately.

No step requires collecting resident records or applying on a resident's behalf. Assistance-provider presence, open appointments and capacity are separate facts to verify.

## Inquiry queue

Run the rows affecting the selected example before broadening the inventory. These are task candidates, not tickets already created or authorization to contact organizations.

| Order | Question | Deliverable and completion criterion |
|---|---|---|
| **1. Demo feasibility** | Which shortlisted program supplies one credible population/program example with available district evidence? | Compare candidate audiences, supported joint measures, missing criteria, uncertainty and comparable uptake availability. Select an example or explain why only an audience claim is supportable. |
| **2. Recent expansions** | Who may still rely on superseded eligibility information? | Verify each selected change's enacted text, effective date, implementation date and current outreach source. Identify changed criteria and a supported outreach audience. Start with POD, ABLE, state EITC, COFA SNAP and Extra Help as relevant. |
| **3. Local uptake** | Can Hawaiʻi evidence replace national or historical context? | Inventory public EITC claims, POD applications/awards, ABLE accounts, WIC age-specific participation and the selected program's administrative measures. Record unit, geography, period, denominator, suppression and availability. A documented data gap is a valid result. |
| **4. Application to use** | Where does assistance stop reaching people? | For the chosen program, distinguish discovery, application, pending decision, approval, receipt/use and renewal where data allow. Pair dated administrative evidence with community accounts and contrary experiences; identify the action each barrier supports. |
| **5. Language and local access** | Does a translated link or nearby office solve the practical barrier? | Verify public navigator contacts, service areas, languages and channels. Investigate Chuukese/Marshallese and Ilocano/Tagalog perspectives; distinguish translated material, intermediary testimony and native-language beneficiary accounts. Record inaccessible perspectives. |
| **6. Capacity** | Will more applications produce assistance or primarily a longer queue? | Record current funding/enrollment limits, provider/retailer access, processing conditions and feasible referrals for the selected program. Mark unresolved capacity in the proposed action. |
| **7. Impact** | What can this read-only product honestly demonstrate? | Define a baseline and evidence for expert-validated mappings, usable referrals or changed staff outreach decisions. Enrollment/approval/redemption improvement requires later comparable agency outcomes and an attribution plan. |

Housing costs and jobs deserve explicit attention. Investigate energy assistance and recognized shelter/utility expenses; verify income periods and self-employment documentation. Use work schedules and nearby provider hours when considering child care. Industry, median income or rent burden alone does not establish program eligibility.

## Program validation cases

These cases add program-specific checks to the district-data guide; they are not a parallel test framework. Implement applicable tests in the actual project using its existing contracts.

| Case | Passing behavior |
|---|---|
| Expanded rule | Uses the rule for the requested benefit period; distinguishes passage, effective date and open applications. |
| ABLE age | Distinguishes current age, disability-onset age and approval date; onset remains unknown in aggregate profiles. |
| Preschool fit | Distinguishes POD, general child-care subsidy, public pre-K and Head Start; verifies the chosen route's ages, hours and provider conditions. |
| Historical EITC rate | Preserves tax year, modeled nature, state geography and federal/state distinction; produces no unsupported district count or dollar total. |
| WIC age gradient | Labels national evidence as national and treats local targeting as a hypothesis pending Hawaiʻi evidence. |
| Expired benefit | Presents HEFAP as historical and uses verified active programs for current referrals. |
| Language/retailer access | Identifies what was checked and provides a usable support route; translated forms or nominal enrollment alone do not establish practical access. |
| Cross-program rules | Keeps each program's household, income, age and resource definitions separate, including Extra Help versus MSPs. |

## Handoff and maintenance

For each completed program inquiry, leave the question answered, source/effective periods, extraction and review status, operational implication, unresolved conditions and next action. Update factual evidence in the [program dossier](../research/benefit-program-access.md); update this guide when inquiry priorities or program-specific checks change. Record adopted scope decisions in [AGENTS.md](../../AGENTS.md).
