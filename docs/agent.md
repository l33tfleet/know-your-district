# Ask runtime decision (#182)

Ask uses TypeSafe's Jev: typed decisions with probabilities and confidence,
not generated text. The local answer contract and renderer in
`app/agent/answers.py` accept IDs and references and render approved copy and
fact-tool results. The provider cannot write figures or prose.

`config.toml` tracks the provider endpoint
`https://api.typesafe.ai/v1/systemone`, model `jev-latest`, timeout 8 seconds,
per-request input allowance 8,192 tokens and daily input-token cap 100,000.
These are operational limits, not demographic figures. `TYPESAFE_API_KEY` is
read from the process environment on each admitted call; production supplies it
through a systemd `EnvironmentFile` outside the repository. Never put it in
TOML, URLs, logs or responses. Missing/blank keys return the existing typed
`Paused` result; application startup still works offline.

`Runtime.run` accepts a trusted client IP and a supplied provider callable.
It permits 10 calls per rolling 60 seconds and 100 per UTC calendar day per
IP. Under one lock it checks both IP limits and reserves the full per-request
input allowance against the global daily cap before invoking the provider.
An exhausted limit returns `Paused` without a provider call. Reservations are
never refunded, even after failures: usage may already be billed. This trades
unused capacity for conservative accounting. The lock is released before the
provider runs. The first admission on a new UTC day clears counters; calls
already in flight remain charged to their admission day.

Only `TimeoutError` and the facade's explicit `ProviderUnavailableError` return
`Paused`. The facade must translate upstream transport/HTTP failures and invalid
upstream responses to `ProviderUnavailableError` at that boundary. Local mapping,
validation and programming errors fail the operation as a fresh `RuntimeError`
carrying only the original exception type name, with its chain suppressed.
The runtime never logs provider exceptions or includes their messages in results.

Deploy with **one worker and one shared Runtime instance**. Counters and IPs
live only in memory until UTC rollover or process exit. Restarts reset every
limit; multiple workers/replicas multiply allowances. This is not a persistent
billing cap. An upstream account spending limit remains an operator safeguard.

This slice makes no HTTP calls and adds no Ask route. Subsequent provider
wiring must enforce the complete serialized input allowance (including state
and questions), timeout, Bearer authentication and typed response validation;
only then is the reservation a bound on billed input. UI wiring renders
`Paused` through the existing canned copy. Never trust arbitrary forwarded IP
headers; configure trusted proxy handling at deployment.

## Recorded outage answers (#390)

The Ask route first runs live classification. A typed `Paused` result (missing
credentials, transport/HTTP failure, timeout, exhausted admission or input budget)
can replay an exact question/chamber/district match. Live refusals, clarifiers
and successful routes are preserved. Unmatched questions retain the paused
notice; replay never interprets an action request as a successful save or edit.
Clarification buttons still resolve their chosen topic without a provider call.

House 22 supports these exact scripts, with SNAP first for story step 3:

- “Where could food-assistance outreach help here?” (`data/ask/story.json`)
- “How many kūpuna live here?” (`data/ask/scripts.json`)
- “Is income higher than the county?” (`data/ask/scripts.json`)

These files store typed routing envelopes and recording dates, not demographic
snapshots. The facade's decoder validates them without transport slots or live
admission. Every replay shows the live-unavailable notice, “Recorded answer, not
live” and the recording date. SNAP cards and district/county/state figures still
read current tool facts, including citations, uncertainty and comparison rules.
Missing local files or invalid recording metadata raise local errors; invalid
provider envelopes retain the decoder’s fail-closed paused behavior.

For an offline rehearsal, set `[ask].force_recordings = true` in `config.toml`
and restart the single worker. This validated boolean bypasses provider calls
and budget reservations; exact scripts replay and unmatched questions pause.
Restore `false` and restart to resume live classification. The default is false.
Briefs, case cards and folder operations remain independent of live Ask.
