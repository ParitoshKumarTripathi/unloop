# UNLOOP

**Customer support that knows when it's wrong.**

A realtime telephone support agent built to survive the moment that breaks most voice
AI: the caller interrupts, corrects you, and the work you already started is now
answering a question they have withdrawn.

---

## The problem

You call your bank because a payment failed. The agent decides your card is blocked.
You say it isn't — you used it twenty minutes ago. The agent says it again. It asks
whether your issue is resolved. You say no. It suggests the card block a third time.
Eventually it hands you to an IVR menu and you start over with a human who knows
nothing.

Everyone has had this call. It is usually described as the AI being "bad at
listening". It is not a language problem. It is a **state-management** problem with
three parts:

1. **No invalidation.** The wrong diagnosis is never marked wrong, so nothing stops it
   coming back.
2. **No staleness.** A tool call issued four seconds ago returns after the correction,
   still looks valid, and gets spoken.
3. **No loop detection.** Nothing counts how many times the same dead end has been
   proposed, so nothing changes strategy.

UNLOOP fixes all three deterministically, in Python, outside the model.

## Why this has to be voice

- **The caller is already on the phone.** Someone holding a failed checkout calls the
  number on their card. The channel is given, not chosen.
- **Corrections arrive mid-utterance.** In chat, the user reads, thinks, and replies.
  On a call they cut in at the word "blocked" — while the agent is speaking, a tool is
  in flight, and a response is already being generated. That overlap *is* the
  engineering problem, and turn-based systems never face it.
- **There is no scrollback.** A caller cannot re-read. What they heard is gone, so
  "what did they actually hear" has to be tracked as state rather than inferred from
  what was generated.

## The claim

> When the caller interrupts and corrects information **while a slow tool call is in
> flight**, UNLOOP stops the obsolete speech, updates state, fences the stale tool
> result and any already-generated response, does not repeat the contradicted
> diagnosis, and produces a final spoken response consistent with what the caller
> actually said and actually heard.

Evidence, method and limitations: **[RIME_EVIDENCE.md](RIME_EVIDENCE.md)**.

**Current status:** 100/100 acceptance runs pass, machine-generated into
`artifacts/results.json`. All measurements to date are in-process. Live-audio
measurements are pending credentials and are recorded as `null`, never estimated.

---

## How it works

```
caller ──▶ LiveKit ──▶ Deepgram nova-3 ──▶ ┌──────────────────────┐
  ▲         (SIP or       (STT, keyterm    │  RESOLUTION ENGINE   │
  │          browser)      boosting)       │  state_version       │
  │                                        │  hypotheses          │
  │                                        │  corrections         │
  │                                        │  ┌────────────────┐  │
  │                                        │  │  STALE FENCE   │◀─┼── tool results
  │                                        │  └────────────────┘  │   (with the version
  │                                        │  loop detector       │    they were issued
  │                                        └──────────┬───────────┘    under)
  │                                                   │
  │                                                   ▼
  │                                                  LLM
  │                                                   │
  │                                        ┌──────────▼───────────┐
  │                                        │  OUTPUT GUARD        │  blocks any sentence
  │                                        │  (in tts_node)       │  asserting a rejected
  │                                        └──────────┬───────────┘  hypothesis
  │                                                   ▼
  └────────────── LiveKit ◀────── Rime coda / WebSocket / 24 kHz
```

The division of labour is the architecture:

- **LiveKit** owns realtime media — turn detection, barge-in, playback truncation.
- **Rime** owns speech — WebSocket streaming, with word timestamps.
- **UNLOOP** owns belief — what is established, what was refuted, what is obsolete.

LiveKit stopping the audio when the caller interrupts is necessary and **not
sufficient**. The audio stops; the tool call issued four seconds ago is still in
flight and the response the LLM already started is still queued. Those are application
state, and nothing in the media stack knows they are now wrong.

### The mechanism, in one paragraph

Every caller correction increments an integer `state_version`. Every asynchronous
thing — each tool call, each generated response — records the version it was born
under. When a late result arrives, the fence compares the two and consults the version
log: if a correction in between invalidated that result's *subject*, it is marked
`stale`, kept as historical evidence, and refused the microphone. If nothing
invalidated it, it is still perfectly good and is used — an OTP delivery check does not
become wrong because the caller corrected you about the card. That distinction is why
the fence is version-aware rather than just discarding everything late.

Details: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
Design record and API audit: **[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)**.

---

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this-repo> && cd unloop
cd agent && uv venv --python 3.12 && uv sync && cd ..
```

The deterministic tests and the full acceptance suite run **with no credentials at
all**:

```bash
bash scripts/run_acceptance_tests.sh
```

### Credentials (needed only for live voice)

```bash
cp .env.example agent/.env.local
# fill in LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET and RIME_API_KEY
```

One setting deserves attention:

```bash
RIME_BASE_URL=wss://users-ws.rime.ai     # ORIGIN ONLY — never append /ws3
```

`livekit-plugins-rime` builds `f"{base_url}/ws3?..."` itself. Rime's own docs quote the
endpoint *with* `/ws3`, so pasting it produces `/ws3/ws3` and fails. UNLOOP strips it
and warns, but the template is correct to begin with.

Verify the configured voice exists in Rime's live catalog:

```bash
python scripts/verify_rime_catalog.py --list-support-voices
```

### Run it

```bash
cd agent && ../agent/.venv/Scripts/python.exe src/unloop/agent.py console   # terminal voice loop
cd agent && ../agent/.venv/Scripts/python.exe src/unloop/agent.py dev       # worker against LiveKit Cloud
```

On macOS or Linux use `agent/.venv/bin/python`. With
[Task](https://taskfile.dev): `task dev` / `task dev-room` / `task test`.

---

## Testing and evidence

| Command | What it does |
|---|---|
| `task test` | 66 deterministic tests — no key, no network, no model |
| `task evidence` | Runs every acceptance scenario, writes `artifacts/` |
| `task acceptance` | Both, plus live catalog verification |
| `task catalog` | Checks the configured voice against Rime's live catalog |
| `task benchmark` | Measures the real Rime path (needs `RIME_API_KEY`) |
| `task preflight` | Secret scan, config check, tests, lint, artifact freshness |

Artifacts, all machine-written:

- `artifacts/results.json` — per-scenario, per-check pass counts and timings
- `artifacts/events/*.jsonl` — the raw event timeline for every run
- `artifacts/rime_config.json` — the exact speech path, endpoint included
- `artifacts/rime_catalog_check.json` — live catalog verification

The Results section of `RIME_EVIDENCE.md` is generated from `results.json` by
`scripts/render_evidence_doc.py`, so it cannot contain a hand-typed number.

Core correctness uses **deterministic assertions**, not LLM judges. A model asked
"did you repeat a rejected diagnosis?" is another chance to get it wrong, correlated
with the mistake being guarded against. LLM judges (`livekit.agents.evals`) grade tone
and completeness only, and are never the sole evidence for an invariant.

---

## Synthetic data

Every customer, card, account, transaction and incident in this repository is
invented. `demo_customer_001` / card ending `4821` is a fixture file, not a person.
There is no real banking system, no real card number and no real phone number
anywhere in the code, the fixtures, the tests or the artifacts.

Event metadata passes through a redactor that scrubs credential-shaped and
phone-number-shaped strings before anything is written, so a leak would need two
independent mistakes.

## Failure behaviour

Documented in full in **[docs/FAILURE_MODES.md](docs/FAILURE_MODES.md)**. In summary:

| Situation | Behaviour |
|---|---|
| A tool times out or errors | The agent says it could not check. It never guesses a value, and no hypothesis is promoted on missing data. |
| A late result is superseded | Marked `stale`, kept as evidence, refused speech. |
| The model tries a rejected diagnosis | Blocked before synthesis; a grounded correction is substituted; a loop signal is raised. |
| Every diagnostic branch is exhausted | Escalation with a structured handoff packet — not another lap. |
| The caller and the backend disagree | Both recorded. The hypothesis is rejected on the caller's testimony, and the conflict is flagged for the human. |
| The caller backchannels ("mhm") | Adaptive interruption keeps the turn going. No state-version change. |
| Rime is unreachable | The session errors rather than silently falling back. There is no shadow TTS provider — see below. |

### Active speech provider

The debug panel shows a **SPEECH: RIME** badge whose contents are read from the live
configuration — model, voice, transport, resolved endpoint, region, sample rate — not
from a hard-coded string. If the provider were ever changed, the badge would say so.

**There is no fallback TTS provider.** That is deliberate: a silent fallback would
mean the judged path could be something other than Rime without anyone noticing. A
Rime failure surfaces as an error, in the logs and on the badge.

## Known limitations

The full list, with reasoning, is in
[RIME_EVIDENCE.md § Limitations](RIME_EVIDENCE.md#limitations). The short version:

1. Measured results are **in-process** — real engine, real fixtures, real injected
   latency, but no audio. They prove the fence logic, not end-to-end audio timing.
2. **Interruption-to-audio-stop is unmeasured.** No target is claimed until a baseline
   exists.
3. "What the caller heard" is derived from LiveKit's synchronised transcript backed by
   Rime word timestamps — close to exact, not exact.
4. Correction extraction is pattern-based: it never invents a correction, but it will
   miss paraphrases outside its patterns.
5. The voice (`eyre`) is a reasoned shortlist pick, **not yet confirmed by a listening
   test**.
6. The Rime region is the plugin default (us-west), **not yet benchmarked** from the
   deployment region.
7. Telephony (SIP) is not yet wired.

## Repository layout

```
agent/src/unloop/
  agent.py            LiveKit AgentSession, tools, tts_node speech gate
  config.py           typed config + the rime_config.json evidence artifact
  prompts.py          written-for-the-ear instructions
  harness.py          deterministic scenario runner (tests AND evidence use this)
  resolution/         state, hypotheses, corrections, stale_fence, output_guard, loop_detector
  tools/              synthetic banking backend, escalation packet, typed results
  fixtures/           fixture loading and the injectable latency table
agent/tests/          66 deterministic tests
fixtures/             the five scenario files
scripts/              acceptance, evidence, benchmark, catalog check, preflight
artifacts/            machine-generated evidence
docs/                 IMPLEMENTATION_PLAN, ARCHITECTURE, FAILURE_MODES, DEMO_SCRIPT
```
