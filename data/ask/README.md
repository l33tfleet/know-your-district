# Ask story recording

`story.json` packages the House 22 food-assistance decision for the November 5,
2026 operator decision on #184. `recorded_on` is the packaging date, not a new
live-provider verification date. The response is copied from #183's
`tests/regressions/fixtures/wo140_model.json` first question: its wire envelope
reconstructs operator-supplied scalar measurements; remaining probabilities and
usage are deterministic fixture data, not a complete live capture.

Only this exact question on House 22 is replayed, and only when
`TYPESAFE_API_KEY` is absent or blank. It goes through the existing Jev facade's
validation and typed routing with an in-memory transport. No credential or
network is needed. Answers display “Recorded answer, not live” and the date.
The recording contains no Census figures or citations: the existing case renderer
reads those from the current read-only fact rows on each request. Other questions
without a key, and live-provider failures with a key, retain the paused notice.
