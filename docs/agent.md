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
