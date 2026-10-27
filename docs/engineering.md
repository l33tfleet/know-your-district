# Engineering principles

The engineering rules for this repo, beside the product rules in `AGENTS.md`. Taken on 2026-10-27 from the
project's house guidance (`engineering_core.md`, snapshot of 2026-10-23). Only the sections that apply to a
read-only web app are here; the numbers are the original ones, so gaps are expected.

**Unattended runs:** #23 says to stop for approval before changing a public interface. Here no one waits: the PR
says `Interface change:` in its first line, with what changes and who uses it, and the reviewer checks it.

## 4. Facade Externals [E]

Wrap every upstream API. Never leak their shapes. When upstream changes, only one file changes, and callers never know.

```
agent -> your facade (your envelope) -> upstream API (their shapes)
```

The facade measures latency per call. Surprises (rate limits, shape changes, downtime) are contained to one file.

This includes platform bindings (R2, S3, GCS, queues, caches). A storage binding is an external dependency with the same risks as any API: vendor lock-in, shape changes, behavioral differences. Even a thin facade (`storage.ts` wrapping `bucket.put`/`bucket.get`) enables testing without the platform and makes migration feasible.

---

## 6. Flat Modules [E]

Each domain = a directory with few files. No inheritance. No shared base classes.

```
books/
  model.py     # data shape
  store.py     # read/write
  commands.py  # CLI entry points
```

Need a second domain? Copy-paste, rename. Extract shared patterns after three domains, not before. Duplication is cheaper than the wrong abstraction.

Flat is not shallow. Each module should hide real complexity behind a small interface. A pile of one-function files moves the complexity into the wiring.

Copies drift when agents edit them: an agent changes one copy and never learns the sibling exists. When you copy, name the siblings in a header comment (`# mirrors films/store.py`). Treat the third copy as the trigger to extract.

---

## 7. Validate Edges, Trust Core [E]

Enums at the boundary. No re-validation inside.

```python
class MediaType(str, Enum):
    BOOK = "book"
    FILM = "film"
    TV = "tv"
    PODCAST = "podcast"

# inside: just use the value
def create_entry(user_id: str, title: str, media_type: MediaType):
    store.insert({"user_id": user_id, "title": title, "type": media_type})
```

Unknown flags, params and enum values fail loudly with a message naming the valid options. Agents hallucinate flags, and a silently ignored flag is the worst outcome: the agent believes it acted.

Validate for security, not just for type. Treat all string inputs as untrusted:
- Reject control characters (ASCII < 0x20), path traversal sequences (`..`) and pre-encoded strings (`%2e%2e`) at the boundary.
- Expect agent inputs to fail differently from human typos: agents embed query syntax in IDs, pre-encode URLs, and confuse path segments.

---

## 8. Privacy in Schema [E]

Visibility, consent and hide-flags belong in the data model, not in app-layer if-statements.

```python
class Entry:
    visibility: str = "private"  # public | followers | private
    hide_rating: bool = False
```

Agents will aggregate and surface data in ways you didn't plan. Schema-level privacy can't be bypassed by a new view.

---

## 12. Secrets Never in Source [E]

Credentials, API keys and tokens always live in environment variables or a secret store. Never hardcode them in source. Rotation must not require code changes or redeployment.

CLI tools should document which env vars they read. SKILL.md should list required auth without including actual secrets.

---

## 13. Characterize Before You Change [E]

Before modifying any external dependency, upstream code or unfamiliar codebase, write characterization tests that document its actual behavior. Not "it should do this": tests that capture what it actually does right now.

These become your safety net. If your changes subtly alter behavior in paths you didn't consider, the characterization tests catch it. This matters most for Principle 4 (Facade Externals): you need to know what the external actually does before you can safely wrap it.

Heuristic: use the code in a test harness. Write an assertion you know will fail. Let the failure tell you what the behavior is. Change the test to expect that behavior. Repeat.

---

## 16. Input Hardening [E]

Treat agent and user input identically: as untrusted. Apply the rigor you'd use for a public web API.

| Threat | Mitigation |
|--------|-----------|
| Path traversal (`../../.ssh`) | Canonicalize and sandbox paths |
| Control characters (< ASCII 0x20) | Reject on input |
| Embedded query params in IDs (`fileId?fields=name`) | Reject `?` and `#` in identifiers |
| Double URL encoding (`%2e%2e`) | Reject `%` in resource names; encode at HTTP layer only |

Validate at the CLI/API boundary. Rejecting bad input is cheaper than recovering from a bad downstream call.

---

## 17. Safety Rails [E]

Every actuator (mutating command) supports a preview that validates inputs and shows what would happen without executing. Destructive operations need explicit intent: `--dry-run` for previews, and for dangerous commands consider preview-by-default with `--commit` to execute.

Build dry-run into the architecture, not into scattered `if dry_run:` checks:
- model actions as data;
- execute them in one place;
- let the preview print the plan that the executor would run.

For multi-step or production changes, review the plan before applying it. Confirmation prompts become a formality.

Agents "think out loud" before acting, and the preview output is what they show the user. The cost of a hallucinated parameter is data loss, not just a bad error message.

For shared-state systems:
- **Soft-delete by default.** Hard deletes in multi-writer systems are dangerous, because one client may be reading what another is deleting. Move deleted items to a trash prefix with TTL cleanup.
- **Document the rollback path** for any feature that writes a new data format to a shared store: how to drain or migrate the data if the feature is removed.

**[V] Untrusted content.** Don't rely on sanitizing prompt injection as a primary defense. Classifiers miss payloads that arrive through tool output. Defend structurally instead:
- least privilege;
- separate read and write credentials;
- sandboxed execution;
- untrusted tool output labeled as data.

---

## 18. Single-Goal Edits [E]

Each commit or patch should make exactly one behavioral change. If you need to change a key format AND add metadata, those are two separate changes, each independently verifiable and independently reversible.

This prevents "thrashing", where a bug could be in either change and you can't isolate which. It also keeps code review tractable and rollback safe.

---

## 19. Edit-Test Cadence [E]

When modifying existing code, run the full test suite after each behavioral change, not just at the end. Document expected test counts at each stage. The edit-test loop should take minutes, not hours.

---

## 21. Staged Deployment [E]

When a shared codebase serves multiple tenants, deploy to the operator's own tenant first, verify, then roll out to the other tenants. Never deploy to all tenants at once without a verification gate.

---

## 23. API Boundary Discipline [E]

Task requires changing a public interface, adding params, extending a type, or reaching through an abstraction? **Stop. Describe the tension. Wait for approval.**

- Implement within existing boundaries first
- No new methods/fields/params on public interfaces without asking
- No internal access to bypass an abstraction that doesn't fit
- No escape hatches: optional any-typed params, overly broad generics, loosened constraints
- No "thin wrappers" that just re-expose internals differently
- If the abstraction is wrong for the task, say so; don't patch around it

Models default to treating boundaries as obstacles. The failure compounds:
1. The boundary doesn't quite fit, so the agent adds a small hole.
2. That repeats across tasks.
3. The abstraction becomes leaky, inconsistent, and load-bearing in conflicting directions.
4. The next refactor hits a wall of accumulated damage.

Instead: "This task needs X but the current interface only exposes Y. Options: (a) extend interface to add X, (b) rethink the boundary, (c) redesign the approach to only need Y. Which direction?"

---

## 25. Move Files by Reference [E]

Never route file bytes through model tokens (base64 in arguments, pasted content). Pass paths, upload handles or URLs, and return a digest (size + hash) so the receiver can verify. Large outputs go to a file, and the command returns its path and a summary.

Model-relayed bytes corrupt silently: every layer reports success while the payload is wrong.

---
