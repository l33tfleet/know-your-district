# Priorities

**Why people use this tool.** They want to serve people, to get benefits delivered more efficiently, and to tell the story of government helping people. Nobody comes to be quizzed on statistics: a figure earns its place by helping someone act for a population. The demo story: type a place → its brief → ask about a group (for example kūpuna) → a cited, justified program match → save and prioritise it → reopen and see what needs attention.
The demo story in .factory/story.md drives the work: a change serves the priorities when it makes a story step work, or clearer or faster for the person in it. Work orders name their **Story step:**.

Know Your District (KevinPlusAgents, DBEDT). Cites: S=Scoring, R=Rules, U=Use case PDF+page.

## Phases
- Until 2026-11-16 09:00 HST: a deployed, reliable app, README and reachable dependency list beat polish; judges score what is live then (S1-2, S4).
- After: demo and presentation. 4 min pitch+demo, 2 min Q&A, hard stop; tech check Nov 20, judging Nov 21 (S4-5).

## Kevin's direction
1. "sort by how often you see the role described in the news media, attention getters win here": legislators, then staff, then officials (U2); higher role wins.
2. "verifiable data should ground everything"
3. "anything that won't make judges go "wow" is out of scope, but there is a baseline "the ground level execution of the foundaitonal work" that is necessary to wow": deployed, reliable, sourced is always in scope.
4. 2026-10-29: the working chat must keep state: prioritized population–program matches. It is a coworker managing case files. Persistent case work belongs in the first complete demo, not a later extension.
5. 2026-10-29: build the whole journey thin first (open a district → understand a case → save and prioritize it → record progress → come back → see what needs attention), then widen it. Work orders labelled journey are done only when their walkthrough video shows the step working.

## Stateful coworker: first complete demo
- A case is a district population × program match, never an individual resident's file. It carries cited evidence and claim limits, priority with rationale, status, dated notes, next steps and suggestion decisions.
- Case records are the durable source of truth. Chat reads and updates those records through validated tools; conversation history alone does not satisfy the requirement.
- The office can set priorities and record progress. The agent uses current case state to propose what to do next, preserves human decisions, and does not repeatedly suggest dismissed work. Existing accept/dismiss behavior remains the basis for agent proposals (#154).
- Acceptance: create and prioritize matches → record an action or decision → close and reopen the folder → ask what needs attention → receive a grounded answer reflecting the saved priorities, progress and decisions. Chat and the visible case list must agree.
- Critical path includes shared match cards (#152), persistent folders (#153), case-aware suggestions (#154), and a ready-to-use demo folder (#155), alongside grounded Ask. News and broader enrichment follow this complete workflow.
- The folder-store rule update (#252) landed in #267. Follow its narrow exception in AGENTS.md; source fact databases remain read-only. This product direction does not itself amend those storage rules.

## Tests
- Wow, or the wow needs it? Else not now.
- Works live, no judge setup (S2)?
- Every figure checkable?

## Use case must-haves
- Web chat agent; summaries for all 51 House, 25 Senate districts (U1, U3)
- Figures cite source, year, geography; flag estimated/apportioned; say missing/old/uncertain; show error margins (U2-4)
- Crosswalk to official boundaries, method explained (U2)
- ESRI/ArcGIS map of districts and indicators (U3-4)
- District vs county vs state; likely eligible vs uptake (U4)
- Programs link official source; agency decides eligibility; kept current (U2-3)
- Exportable sourced one-pager (U4)
- Public aggregate data; populations not individuals; nonpartisan; data licences checked (U2-3)
- WCAG 2.1 AA, plain language, ʻokina and kahakō (U3)
- Documented tests proving mapping and eligibility accuracy (U3)
- Security/privacy note, solution-specific, max 300 words (S3, R5)
- One population+program pair where outreach could raise uptake (U5)

## Scoring
Tech (S3, R7): 2 judges x 6 categories x 5: Technical Implementation, Functional Evaluation Video (max 10 min/50 MB, S2), Working Prototype, Innovation and Excellence, User Experience, Security/Privacy. 60% to be eligible to present, not certain (S4).
Presentation (S5, R7): 4 x 5: Requirements, Originality & Design, Utility & Impact, Presentation & Delivery; a skipped category scores 0. Final = mean of both percentages.

## Submission rules
- Judges do no setup: no databases, sign-ups, startup debugging (S2); may score from description, images, demo, video alone (R8).
- README: access/run steps, dependencies, config, known limits (S2).
- Third-party APIs, models, datasets, hosted services listed and reachable during review (S2).
- No secrets in GitHub or the form; give judges access directly (S1).
- Public repo, open source license (R5); only post-kickoff work counts (R3).

## Sources (not committed)
- S: `HAIC-2026-Scoring-Criteria.pdf`, also https://HAIC.hawaii.gov/HAIC-judging-criteria/
- R: `HAIC-2026-Official-Rules-and-Guidelines.pdf`
- U: `HAIC_Use_Case_Know_Your_District_AI_Agent_2026.pdf`
