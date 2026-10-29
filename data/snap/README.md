# SNAP source artifacts

This directory is isolated from the core fact database. It contains published
B22003_006E estimates and B22003_006M margins of error from the U.S. Census
Bureau, ACS 2020–2024 five-year release, for the 2022-plan House and Senate
districts, the four county geographies and the state. Kalawao is excluded from
the county outputs and remains part of state and district totals.

The source is the official table-based summary file. Observation API requests
without a key redirected to Census's missing-key page during this run; the
metadata endpoint and public bulk download remained accessible. Each fact's
method identifies the actual bulk source URL. `provenance.json` records the
retrieval date, original full-file checksum, geography mapping and limitations.
`evidence/b22003-hawaii.dat` preserves the published header and selected source
lines, including Kalawao's excluded county line. The summary file does not
supply annotation columns; the stored method records this limitation.

The independent golden fixture is
`tests/regressions/fixtures/wo136_snap.json`. It preserves the original House
district source line, header and metadata. The oracle reads the estimate and
published 90% MOE directly from that line, without importing production
conversion, geography or reliability code. It does not subtract estimates or
combine MOEs. The replay builder separately uses named source columns and the
production fact converter. `make check` verifies exact geography coverage,
cell provenance, the independent district match, canonical database/TSV bytes,
and evidence checksums without network access.

```sh
# Independently retrieve a fresh golden; review before replacing the fixture.
uv run python -m scripts.independent_snap --fetch > /tmp/snap-golden.json
# Validate the committed source excerpt before publishing a replay.
uv run python -m scripts.independent_snap --build-summary --dry-run
uv run python -m scripts.independent_snap --build-summary
make snap-check
```

The HTML files are dated source evidence, never application templates.
`referrals.json` records the rules review and assistance contact/service areas
verified against DHS and Aloha United Way. The DHS landing-page outreach link
has an older fiscal-year label; the linked directory explicitly identifies its
current effective period. Coverage for Molokaʻi and Lānaʻi is not inferred from
a Maui listing: use the statewide DHS line or 211 for routing. Verification was
by published web evidence; no provider was contacted and availability is not
guaranteed.

SNAP may help; DHS decides eligibility. This ACS joint poverty/nonreceipt cell
is a lower-bound outreach indicator using national Census poverty thresholds,
not a count of eligible households. Survey responses undercount benefit
receipt. The rule summary is not a complete eligibility checklist. Official
sources and verification dates accompany the referral records. Removing this
directory rolls back these isolated artifacts; the app continues using its
core fact database.
