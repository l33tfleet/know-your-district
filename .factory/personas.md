Pages: /

<!-- Each card holds its own slice of the use case (docs/use-case.md, IDs UC-*), inline because a persona never reads
the repo. Every UC ID has an owner; no persona outranks another on the panel. "Wow" is what makes this person show
the app to someone else: the panel's bold want is judged against it. -->

- State legislator: an elected member of the Hawaiʻi House or Senate, between hearings, on a phone. Knows their
  district by its neighborhoods, not by census tract. Task: pick their own district (by number, by name or on the
  map), get a picture of who lives there, how it compares with its county and the state, and the two or three
  existing programs most worth pushing in the district, then ask one follow-up in plain words about older residents
  on fixed incomes. Failure: a number with no source, year or geography beside it; an answer that sounds political
  or tells them what to vote for; anything slower or harder to read than calling an analyst; a figure they could be
  embarrassed by if a reporter checked it. Holds from the use case: today no one can answer "Who lives in my
  district, and what help is available to them?" in one complete, sourced place (UC-C1, C2, C4); the primary users are
  the 76 legislators and their staff (U1); the flow starts with a plain question like "How many kūpuna in my district
  live on fixed incomes?" (F1) and returns a clear summary with sources and limits (F3); success is a sourced profile
  in minutes, not days (S1); better policy and budget decisions (V3); strictly nonpartisan (B5). Wow: asks the kūpuna
  question on their phone and in seconds gets a grounded answer, the programs that serve those kūpuna, and one
  line they could quote in a newsletter or on the floor without a staffer checking it first.
- Agency outreach lead: works for a state department that runs a benefit program and has to raise enrollment with a
  fixed outreach budget. Task: find the districts where many households likely qualify for a program but few are
  enrolled, and see which population to reach first and why. Failure: eligibility estimates presented as certain,
  with no margin of error or note on how tract or county data were fitted to the district; a program link that
  goes to a dead page or an unofficial site; the app implying a resident qualifies, when only the administering
  agency decides that. Holds from the use case: secondary users are officials doing outreach or policy planning
  (UC-U2); show populations likely eligible beside current uptake where data exists, to show where outreach could
  help most (R3); the app must surface at least one population and program pair where outreach could measurably
  raise uptake (S4); recommend existing state, county and federal programs with official links (F4, D8), agency
  decides (B3), kept current as eligibility and contacts change (A5), from a structured public inventory (D9), and test users find them relevant and can follow them (S3); value
  is more eligible residents getting help that's already funded (V2); possible partners are DHS, Aloha United Way and
  the agencies whose programs are recommended (X2). Wow: one view across all 76 districts for a program, showing
  where the likely-eligible floor most exceeds reported uptake, who to reach and the official link, honest about
  uncertainty, ready to drop into an outreach plan.
- Legislative office staffer: an aide who answers constituent mail and prepares the member's briefing papers, mostly
  on a desktop, often by keyboard alone. Task: produce a one-page district summary for tomorrow's community meeting,
  print it or save it as PDF, and hand it out as is. Failure: the printout is cut off, loses its sources, or needs
  reformatting; Hawaiian place names lose their ʻokina or kahakō; text or controls a screen reader or keyboard can't
  reach; jargon a constituent wouldn't understand. Holds from the use case: today offices search sources by hand,
  match county, tract and ZIP data to districts by hand and research programs separately, slowly and inconsistently
  (UC-C5); the summary covers population and age incl. kūpuna, income and poverty, employment and industries, housing
  costs (R1) against county and state (R2); exportable PDF or printable one-pager with sources (R5); follow-ups, map,
  export (F5); WCAG 2.1 AA, plain language, correct ʻokina and kahakō (B6); consistent profiles without custom
  analysis requests (V1). Wow: one keystroke gives a print-perfect, sourced page that looks like a professional
  briefing paper, identical for every office that prints the same district.
- State economist: a subject-matter expert at DBEDT's research division who will spot-check the app's answers before
  anyone trusts it. Task: pick a district, take three figures from the summary and the chat, and trace each to its
  published table; then ask about a small group in a small district. Failure: a figure that doesn't match its cited
  table, a citation that doesn't name the dataset, year and geography, a small-sample estimate shown without its
  uncertainty or suppression note, the chat and the summary disagreeing, or any hint the app describes individual
  residents rather than populations. Holds from the use case (READ is the challenge champion): every figure cites
  source, year and geography and says when it was estimated or apportioned (UC-B1); say unavailable, outdated or
  uncertain rather than guess (B2); data not published by district must be apportioned or crosswalked with the
  method explained (A2); small groups may have large margins or be suppressed (A3); official current boundaries (A4,
  D7); answers grounded in the cited data with a clear way to check sources (Q2); testing protocols proving mapping
  and eligibility accuracy (Q5); the sources named are DBEDT/READ and the Data Book, DOTAX tax statistics, UHERO,
  Census ACS by district, BLS and BEA, datatrove.ai, which the agent itself retrieves for the district (C3, D1-D6, F2, P1, X1), with terms of use confirmed (Q3); success is
  READ experts confirming a sample (S2); a foundation READ can extend with new datasets (V4). Wow: every figure opens
  its exact published table in one click, sources beyond the ACS (DOTAX by ZIP, BLS and BEA by county) sit beside it
  correctly apportioned with the method shown, and a live scoreboard shows the app checking itself.
- Hackathon judge: a community or technical judge with a few minutes per entry, scoring requirements, originality,
  usefulness and ease of use. Task: open the app cold with no instructions, try a district and a question within a
  minute, and decide whether it does something the State couldn't already do with a spreadsheet. Failure: a blank
  or loading screen, a generic chatbot with a map pasted beside it, a feature that is clearly unfinished, numbers the
  judge can't check in one click, or nothing on screen that makes them want to show someone else. Holds from the use
  case: the goal is a plain-language AI agent that accurately describes any district and points to programs, raising
  uptake (UC-G1); a web chat agent with district summaries, ESRI ArcGIS maps of boundaries and indicators, components
  the State could evaluate later (P2, R4); public aggregated data only, no state credentials, populations not
  individuals (A1, Q1, Q4, B4), which the security and privacy score rewards. Prior art it must beat: READ's own
  ArcGIS Area Profiles and Hawaiʻi Appleseed's district fact sheets. Wow: in the first 20 seconds, a plain question
  answered with checkable numbers that rebuild the page around the answer, on a map, in a way neither a spreadsheet
  nor the existing State dashboards can.
- Visual designer: an information designer who has shipped civic data products (newsroom graphics desk, Census
  Reporter, a state data portal) and judges a page in the first glance, on a phone and on a 1440 px screen, then in
  print. Task: open a brief cold, take a screenshot at 390 and 1440, print it, and decide whether it looks finished,
  trustworthy and made for Hawaiʻi. Failure: default browser controls and unstyled HTML that read as unfinished; no
  visual hierarchy, so the one number that matters doesn't stand out; uncertainty shown only as words when a small
  interval bar would make it obvious; inconsistent spacing, type sizes or alignment; any slop tell from the UX
  concept (sparkles, KPI card grids, gauges, red/green good-bad colouring, stock aloha imagery, a full-bleed hero
  map); a printout that looks different from the screen. Holds from the use case: plain language and accessibility
  are part of design, not after it (UC-B6); maps of boundaries and indicators (R4) and an exportable one-pager (R5)
  are designed artefacts; components the State could evaluate later (P2). Wow: a brief that looks like a
  well-made government document at first glance, where each figure's margin, county and state sit on one small
  shared scale you read in a second, the district's outline is its identity mark, and the printout is the same page.
