# Priorities

What to weigh when judging whether a change or a piece of feedback serves Know Your District (team KevinPlusAgents, DBEDT challenge). Cites: Scoring, Rules, Use case = the official PDFs listed under Sources, with page.

## Phase, by date
- **Until 2026-11-16 09:00 HST: foundation.** Judges score what is live then and may not rescore later changes (Scoring p1, p4). A deployed, reliable app, a README and a reachable dependency list beat any polish (Scoring p2; Rules p4).
- **After that: demo and presentation.** 4 minutes of pitch and live demo, then 2 of Q&A, hard stop (Scoring p5). Work that makes the demo land or covers a presentation category wins. Tech check Nov 20, judging Nov 21 (Scoring p4).

## Kevin's direction
1. Audience: "sort by how often you see the role described in the news media, attention getters win here". So legislators first, then their staff, then officials doing outreach or policy (users: Use case p2). The higher role wins a conflict.
2. Truth: "verifiable data should ground everything". No figure without a source a judge can check.
3. Scope: "anything that won't make judges go "wow" is out of scope, but there is a baseline "the ground level execution of the foundaitonal work" that is necessary to wow". Deployed, reliable and sourced is that baseline, so it is always in scope.

## Tests
- Will it make a judge say "wow", or does the wow depend on it? Neither: not now.
- Does the live app still work for a judge who does no setup (Scoring p2)?
- Does every figure shown cite source, year and geography, and flag estimates (Use case p3)?

## Technical review (Scoring p3; Rules p7)
Two judges, 6 categories x 5 points each. 60% of the total makes the team eligible to present, not certain (Scoring p4).
- Technical Implementation: tools used well to meet user needs
- Functional Evaluation Video: shows what it does; max 10 min / 50 MB (Scoring p2)
- Working Prototype: deployed, and works as the repo and form describe
- Innovation and Excellence: new or inventive use of existing tech
- User Experience: intuitive, easy
- Security/Privacy: specific to this app, max 300 words, on the form

## Presentation (Scoring p5; Rules p7)
4 categories x 5 per judge: Requirements, Originality & Design, Utility & Impact, Presentation & Delivery. A category the pitch skips scores 0. Final score = mean of the technical and presentation percentages.

## Submission rules
- Judges set nothing up: no databases, sign-ups or debugging startup (Scoring p2). They need not test it and may score from description, images, demo and video alone (Rules p8).
- README: how to access or run it, dependencies, configuration, known limits (Scoring p2).
- Every third-party API, AI model, dataset or hosted service is listed and reachable during review (Scoring p2).
- No secrets in GitHub or the form; give judges access directly (Scoring p1).
- Public repo, open source license (Rules p5). Only work made after kickoff counts (Rules p3).

## Use case requirements (Use case)
- Chat agent with summaries for all 51 House and 25 Senate districts (p1, p3).
- Each figure: source, year, geography, and whether estimated or apportioned to the district. Say when data is missing, old or uncertain; no false precision (p2-3).
- Crosswalk tract, ZIP or county data to official boundaries and explain how (p2).
- Public, aggregated data only; describe populations, never individuals; nonpartisan (p2-3).
- Programs are informational and link to the official source; the agency decides eligibility; program data kept current (p2-3).
- WCAG 2.1 AA, plain language, correct ʻokina and kahakō (p3).
- A test protocol showing mapping and eligibility results are accurate (p3).
- Outputs: district vs county vs state, likely eligible vs current uptake, map, exportable sourced one-pager (p4).
- Success: a sourced profile in minutes; experts confirm sampled figures; at least one population and program pair where outreach could raise uptake (p5).

## Sources (not committed)
- Scoring: `HAIC-2026-Scoring-Criteria.pdf`, also https://HAIC.hawaii.gov/HAIC-judging-criteria/
- Rules: `HAIC-2026-Official-Rules-and-Guidelines.pdf`
- Use case: `HAIC_Use_Case_Know_Your_District_AI_Agent_2026.pdf`
