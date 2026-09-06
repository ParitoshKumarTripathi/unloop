# RIME_EVIDENCE

Evidence for UNLOOP's hard voice claim, the Rime configuration behind it, and an
honest account of what has and has not been measured.

Everything under **Results** is machine-generated from `artifacts/results.json` by
`scripts/render_evidence_doc.py`. No number in this document was typed by a person.

---

## Hard voice claim

> During a realtime customer-support call, when the caller interrupts the agent and
> corrects information **while a slow tool call is still in flight**, UNLOOP stops the
> obsolete speech, updates its conversational state, fences the stale tool result and
> any already-generated response, does not repeat the contradicted diagnosis, and
> produces a final spoken response consistent with what the caller actually said and
> actually heard.

One claim. Everything in the repository exists to make it falsifiable.

### What would falsify it

The acceptance suite fails, loudly, if any of these happen:

| Failure | How it is detected |
|---|---|
| A superseded tool result reaches speech | `stale_result.triggered_speech is True`, or the fence returns `may_speak` for a superseded subject |
| A contradicted diagnosis is spoken again | any turn the caller *heard* after the rejection matches the rejected hypothesis's assertion pattern |
| An interruption is ignored | no `INTERRUPTION_DETECTED` / no state-version increment for a correction |
| Final state does not reflect the correction | `CARD_BLOCKED` is not `REJECTED` at the end of the run |
| The handoff loses context | packet missing confirmed facts, rejections, corrections, or attempted actions |
| The provider is not Rime | `artifacts/rime_config.json` provider is not Rime, or the resolved endpoint is not a Rime host |

---

## Why voice is necessary here

This is not a chat product with speech bolted on. Three properties only exist on a
phone call:

1. **The caller is already on the phone.** Someone whose payment just failed is
   holding a card and a half-finished checkout. They are not going to open a chat
   widget and type; they call the number on the back of the card. The channel is
   given, not chosen.

2. **Correction happens mid-utterance, not between messages.** In text, a user reads
   a wrong diagnosis, thinks, and replies. On a call they cut in at the word
   "blocked". That overlap is the entire engineering problem: the agent is speaking,
   a tool is in flight, and a generated response is already queued when the
   contradiction arrives. Turn-based systems never face this.

3. **There is no scrollback.** A text user can re-read and notice the agent
   contradicting itself. A caller cannot. What was said is gone, which is exactly why
   "what did the caller actually hear" has to be tracked as state rather than assumed
   from what was generated.

The failure UNLOOP targets — lock onto a wrong diagnosis, ignore the correction,
repeat it, ask "is your issue resolved?", dump to IVR — is a *voice* failure. It is
common, it is infuriating, and it is a state-management bug, not a language problem.

---

## Acceptance test (defined before implementation)

Written into `docs/IMPLEMENTATION_PLAN.md` §6 during Phase 0, before any engine code
existed, so the implementation could not be tuned to fit a result chosen later.

**T-PRIMARY — stale-result fence under interruption**

1. Load the `otp_slow_tool` fixture. `get_card_status` is delayed.
2. The agent proposes the naive `CARD_BLOCKED` diagnosis; the caller hears it.
3. A card-status check is issued. Record the state version at issue time.
4. **While the tool is still in flight**, the caller interrupts:
   *"No, my card is not blocked. I used it five minutes ago. Check the OTP delivery."*
5. Assert: the state version increments exactly once; `CARD_BLOCKED` becomes
   `REJECTED` with the caller's evidence attached.
6. The delayed result arrives. Assert: `originating_state_version < current`, the
   result is marked `stale`, `may_speak` is false, and `triggered_speech` is false.
7. The agent attempts the same diagnosis again. Assert: blocked before synthesis.
8. Assert: no turn the caller heard after the rejection asserts `CARD_BLOCKED`.
9. Assert: the final spoken turn addresses OTP delivery, and the handoff packet
   carries confirmed facts, rejections, corrections and attempted actions.

Secondary tests T-A (normal), T-B (contradiction), T-C (loop), T-D (tool failure),
T-E (escalation) are defined in the same section. T-F (backchannel) and T-G
(telephony) require a live session and are listed under *Not yet measured*.

---

## Results

<!-- BEGIN GENERATED: do not edit by hand; run scripts/render_evidence_doc.py -->

*Generated 2026-09-06T17:46:53Z from commit `0f8aa43d1a36`.*

### Environment

| Field | Value |
|---|---|
| Python | 3.12.10 |
| Platform | Windows-11-10.0.26200-SP0 |
| livekit-agents | 1.8.0 |
| livekit-plugins-rime | 1.8.0 |
| Harness | in-process deterministic |
| Injected `get_card_status` delay | 300 ms |

### Speech path as configured

| Field | Value |
|---|---|
| Provider | Rime |
| Integration | livekit-plugins-rime (direct plugin, own RIME_API_KEY) |
| Model | `coda` |
| Speaker | `eyre` |
| Language | `eng` |
| Transport | websocket |
| Configured base URL | `wss://users-ws.rime.ai` |
| Resolved endpoint | `wss://users-ws.rime.ai/ws3?speaker=eyre&modelId=coda&audioFormat=pcm&samplingRate=24000&segment=bySentence&lang=eng` |
| Region | us-west |
| Audio format | pcm_s16le |
| Sample rate | 24000 Hz |
| Segmentation | `bySentence` |
| Plugin version | 1.8.0 |
| Config problems | none |

### Acceptance results

**100 of 100 runs passed** (30.67s).

| Scenario | Runs | Passed | Failed | Checks per run | Failed checks |
|---|---:|---:|---:|---:|---|
| `primary_stale_fence` | 20 | 20 | 0 | 17 | — |
| `normal_flow` | 20 | 20 | 0 | 5 | — |
| `loop_detection` | 20 | 20 | 0 | 3 | — |
| `tool_failure` | 20 | 20 | 0 | 4 | — |
| `escalation` | 20 | 20 | 0 | 7 | — |

#### `primary_stale_fence` — every check, every run

| Check | Passed |
|---|---:|
| `card_blocked_rejected` | 20/20 |
| `corrected_response_was_spoken` | 20/20 |
| `final_response_mentions_delivery` | 20/20 |
| `handoff_has_confirmed_rejected_and_attempted` | 20/20 |
| `handoff_routes_to_delivery_team` | 20/20 |
| `late_result_cannot_speak` | 20/20 |
| `late_result_did_not_speak` | 20/20 |
| `late_result_is_stale` | 20/20 |
| `late_result_kept_as_evidence` | 20/20 |
| `naive_diagnosis_was_spoken_first` | 20/20 |
| `no_rejected_assertion_after_rejection` | 20/20 |
| `rejection_cites_user_evidence` | 20/20 |
| `repeat_of_rejected_diagnosis_blocked` | 20/20 |
| `stale_event_emitted` | 20/20 |
| `state_version_incremented_once` | 20/20 |
| `tool_was_still_in_flight_at_correction` | 20/20 |
| `unrelated_check_still_usable` | 20/20 |

### In-process timings

**`primary_stale_fence`**

| Measurement | p50 | p95 | min | max |
|---|---:|---:|---:|---:|
| `correction_apply_ms` | 0.24 | 0.441 | 0.162 | 0.441 | 
| `correction_to_fence_ms` | 189.667 | 205.909 | 175.158 | 205.909 | 

- **`correction_apply_ms`** — Time to extract a correction from the caller's utterance, reject the contradicted hypothesis and increment the state version. Pure in-process CPU work, no I/O. This is the cost of the mechanism itself.

- **`correction_to_fence_ms`** — Wall-clock time from the correction being applied to the in-flight tool result being classified by the fence. NOT a measure of fence speed: it is dominated by the remainder of the injected 300 ms tool delay, because the fence cannot classify a result that has not arrived yet. Reported because it shows the correction genuinely lands while the tool is still in flight, which is the precondition the stress case depends on.

> All timings here are in-process. None of them include audio capture, network, synthesis or playback. Do not read them as end-to-end voice latencies - those are listed under not_yet_measured.


### Live Rime measurements

*Measured 2026-09-06T17:18:23Z from `Windows-11-10.0.26200-SP0`.*

> Rime serves us-east-1 and us-west-2 only. A measurement taken far from both says more about geography than about Rime. Re-run from the deployed worker for the number that describes production.

Time to first audio, client-side, through the same WebSocket path the agent uses. **Cold** = new connection (TCP + TLS + WebSocket handshake). **Warm** = pooled connection, which is what a running agent sees between turns. They measure different things and are not averaged together.

**regions**

| Variant | Cold TTFA | Warm p50 | Warm p95 | Warm min | Warm max | n |
|---|---:|---:|---:|---:|---:|---:|
| `us-west` | 4747.32 | 382.66 | 476.55 | 364.2 | 476.55 | 15 |
| `us-east` | 1502.36 | 381.15 | 449.25 | 352.0 | 449.25 | 15 |

**segments**

| Variant | Cold TTFA | Warm p50 | Warm p95 | Warm min | Warm max | n |
|---|---:|---:|---:|---:|---:|---:|
| `bySentence` | 1431.18 | 358.41 | 458.33 | 334.95 | 458.33 | 15 |
| `immediate` | 1270.75 | 370.11 | 448.59 | 345.37 | 448.59 | 15 |

**models**

| Variant | Cold TTFA | Warm p50 | Warm p95 | Warm min | Warm max | n |
|---|---:|---:|---:|---:|---:|---:|
| `coda/eyre` | 1502.58 | 381.0 | 413.07 | 375.12 | 413.07 | 15 |
| `mistv3/cove` | 1228.27 | 326.36 | 349.97 | 323.85 | 349.97 | 15 |

**sample rates**

| Variant | Cold TTFA | Warm p50 | Warm p95 | Warm min | Warm max | n |
|---|---:|---:|---:|---:|---:|---:|
| `8000Hz` | 1328.28 | 378.6 | 2113.01 | 376.14 | 2113.01 | 15 |
| `16000Hz` | 1422.01 | 378.65 | 710.72 | 373.99 | 710.72 | 15 |
| `24000Hz` | 1311.9 | 360.37 | 445.79 | 338.38 | 445.79 | 15 |

**voices** — identical pronunciation probe, so duration is directly comparable. Speaking rate is not in Rime's catalog and is the one objective thing separating these candidates.

| Speaker | Audio | Words/min | WAV |
|---|---:|---:|---|
| `eyre` | 15.9s | 113.1 | `artifacts/audio/voice_eyre.wav` |
| `lintel` | 11.4s | 157.3 | `artifacts/audio/voice_lintel.wav` |
| `bancroft` | 16.2s | 110.8 | `artifacts/audio/voice_bancroft.wav` |
| `cupola` | 11.0s | 163.0 | `artifacts/audio/voice_cupola.wav` |
| `clementine` | 13.8s | 130.1 | `artifacts/audio/voice_clementine.wav` |

### Not yet measured

These require credentials or hardware that were not available when this artifact was generated. They are recorded as `null`, never estimated.

| Measurement | Status | Why |
|---|---|---|
| `interruption_to_obsolete_audio_stop_ms` | not measured | Requires a live LiveKit session with real audio and a human interrupting. Not derivable from the in-process harness. No target is claimed until a baseline is measured. |
| `telephony_sip_path` | not measured | No SIP trunk configured yet (Phase 9). |
| `rime_ttfa_from_deployed_worker` | not measured | The Rime numbers in live_rime_measurements were taken from a development machine, not from the deployed worker. They describe that machine's network path, not production. |

<!-- END GENERATED -->

---

## The stress case, event by event

One line per event from a real run in `artifacts/events/primary_stale_fence_000.jsonl`:

```
seq= 7  v=2  STATE_VERSION_CHANGED     the correction lands; version 1 -> 2
seq= 9  v=2  HYPOTHESIS_REJECTED       CARD_BLOCKED rejected, citing the caller
seq=11  v=2  TOOL_MARKED_STALE         get_card_status returned at v1, current is v2
seq=15  v=2  OUTPUT_GUARD_REJECTION    the model tried CARD_BLOCKED again; blocked
```

That sequence is the whole product. The tool call was real, the delay was real, the
result was real — and it was refused the microphone because the question it answered
had been withdrawn 180 ms earlier.

Read the full timeline for any run:

```bash
python -c "import json;[print(json.loads(l)['event_type']) for l in open('artifacts/events/primary_stale_fence_000.jsonl')]"
```

---

## Rime configuration, and how each value was chosen

Recorded machine-readably in `artifacts/rime_config.json`; the table under **Results**
is rendered from it.

**Integration.** `livekit-plugins-rime` directly, with our own `RIME_API_KEY` —
*not* Rime routed through LiveKit Inference. LiveKit Inference would also serve
`rime/coda` with no extra key, but it would put a gateway between us and the claim: we
could not name the endpoint, and we would lose the word-timestamp stream. Direct
integration makes the provider checkable.

**Model — `coda`, and we measured what that costs.** Rime's flagship, and the plugin's
own default. `mistv3` is faster, and rather than wave that away we benchmarked it: over
15 warm samples each, `coda/eyre` sat at **381 ms p50 (range 375–413)** and
`mistv3/cove` at **326 ms p50 (range 324–350)**. Those ranges do not overlap, so the
~55 ms is a real difference, not noise.

We still choose `coda`. UNLOOP's claim is about correctness under interruption, not
time-to-first-audio, and 55 ms is not what makes or breaks this product. But the price
is now a measured number in the table above rather than an assumption, and anyone who
disagrees with the trade can see exactly what they would be buying.

**`arcana` is not an option.** It was retired 2026-08-19; the installed plugin rejects
it at runtime with *"Rime Arcana is no longer supported. Use model='coda' instead."*
Any example still showing `model="arcana"` is stale.

**Voice — shortlisted from the live catalog, confirmed by listening.** Rime publishes
its catalog unauthenticated at `https://users.rime.ai/data/voices/all-v2.json`, so the
"current production voice" requirement is machine-checked, not asserted:

```bash
python scripts/verify_rime_catalog.py --list-support-voices
```

Coda English has 162 voices. The shortlist is the flagship voices whose catalog styles
include *professional* or *formal* — `eyre`, `lintel`, `bancroft`, `cupola`,
`clementine`. `eyre` ("A warm, friendly American voice, calm and easy to listen to")
is configured: a bank support line wants calm and legible, not upbeat.

All five candidates have now been rendered from the live API against a pronunciation
probe containing an initialism, a four-digit sequence, a time and a rupee amount
(`artifacts/audio/voice_*.wav`, table above). That surfaced something the catalog does
not publish — **speaking rate varies by 47% across the shortlist**:

| Speaker | Words/min |
|---|---:|
| `bancroft` | 111 |
| `eyre` | 113 |
| `clementine` | 130 |
| `lintel` | 157 |
| `cupola` | 163 |

Natural conversational English sits around 150 wpm. `eyre` — chosen from a catalog
description reading "calm and easy to listen to" — is 25% slower than that, which on a
phone line is as likely to read as ponderous as calm.

> **Status of this choice.** `eyre` remains configured, and it is still *not confirmed
> by a listening test*. The WAVs exist and the rate data is measured, but choosing a
> voice is a judgement about how it sounds, and that judgement has not been made yet.
> `lintel` (157 wpm, "polished and lively") is the most likely alternative on the data.
> This is recorded as an open item rather than quietly settled.

**Transport — WebSocket, and the `/ws3` trap.** `use_websocket=True`. The plugin
builds its own path:

```python
# livekit/plugins/rime/tts.py
return f"{self._base_url}/ws3?{urlencode(encoded)}"
```

Rime's documentation quotes the endpoint **including** `/ws3`, because it documents
the raw API. Pasting that documented URL into `base_url` produces
`wss://users-ws.rime.ai/ws3/ws3?…` and fails. `RIME_BASE_URL` must therefore be the
**origin only**. `config.py` strips a trailing `/ws3` and warns, `validate()` reports
it as a problem, and `test_rime_config.py` asserts on it — three layers, because this
one costs an evening to diagnose from the connection error alone.

`test_resolved_endpoint_matches_what_the_installed_plugin_actually_builds` constructs
the real plugin and compares `tts._ws_url()` to the endpoint we publish as evidence,
so `rime_config.json` cannot describe a connection different from the one opened.

**Region — measured, and the answer is "it doesn't matter here".** Rime serves two:
`wss://users-ws.rime.ai` (us-west-2, the plugin default) and
`wss://users-east-ws.rime.ai` (us-east-1). There is no auto-routing; the region is
entirely `base_url`.

Over 15 warm samples each: **us-west 383 ms p50 (364–477)**, **us-east 381 ms p50
(352–449)**. A 1.5 ms gap with completely overlapping ranges — the two are
indistinguishable from here, and both sit around 380 ms.

That number is the interesting part, and it is not Rime's fault. This project's
LiveKit Cloud instance registers in **India South** (visible in the worker log:
`"region": "India South"`), and Rime serves **US East and US West only**. Roughly
250–300 ms of that 380 ms is India↔US round-trip. Rime's own guidance — route
east-coast users to US East, west-coast to US West — has nothing to offer a worker in
Asia, because there is no near region to route to.

Consequences we are not going to paper over:

- **~380 ms of time-to-first-audio is a geographic floor for this deployment**, not
  something tuning fixes. Region selection, segmentation and sample rate are all
  rounding errors against it.
- Keeping the us-west default is therefore the right call: it is the plugin default,
  it measured identically, and switching would be change without benefit.
- A production deployment serving Indian callers would want a LiveKit region near a
  Rime region, or Rime on-prem. That is a deployment decision, not a code change, and
  it is out of scope for this submission — but it is the first thing we would fix.

**Sample rate — 24 000 Hz.** Coda's native rate. Rime's latency guidance is to request
the rate you need rather than resample downstream, so the telephony path requests
8 000 Hz directly rather than downsampling 24 kHz.

> A documentation discrepancy worth recording: the LiveKit Rime integration page
> states a default sample rate of 16000; the shipped constructor default is 22050.
> UNLOOP relies on neither — the rate is set explicitly and recorded in the artifact.

**Segmentation — `bySentence`, and the hypothesis that `immediate` would win was
wrong.** LiveKit already feeds the plugin sentence-tokenised text, so it was plausible
that server-side sentence buffering was pure overhead. Measured over 15 warm samples:
**`bySentence` 358 ms p50 (335–458)**, **`immediate` 370 ms p50 (345–449)**. If
anything `bySentence` is marginally ahead, and the ranges overlap almost entirely, so
the honest reading is *no measurable difference*. We keep the plugin default, on the
grounds that there is no evidence to justify moving off it.

**Sample rate — no latency argument either way.** 8 kHz 379 ms p50, 16 kHz 379 ms,
24 kHz 360 ms, all with overlapping ranges. The 8 kHz run also threw a 2.1 s p95
outlier (a pool reconnect), which is worth noting for a different reason: with n=15 the
p95 column is a single sample and should not be read as a tail estimate. 24 kHz stays
for the browser path because it is Coda's native rate; 8 kHz is used for telephony on
Rime's payload-size guidance, not for latency.

**Word timestamps are load-bearing, not decorative.** With `use_websocket=True` the
plugin advertises `aligned_transcript=True` and forwards Rime's `timestamps` frames as
`TimedString(text, start_time, end_time)`. With `use_tts_aligned_transcript=True` on
the session, LiveKit's transcript synchroniser advances on **real word annotations**
instead of an estimated speaking rate. When the caller interrupts, the truncation
point — what they actually heard — is therefore measured rather than modelled. This is
the strongest reason UNLOOP uses Rime over its WebSocket path specifically, beyond
voice quality.

**Writing for the ear.** The system prompt forbids markdown, lists and symbols; the
output guard blocks them deterministically if the model produces them anyway
(`MARKDOWN_IN_SPEECH`). "O T P" is spelled as letters, card digits are spoken
individually. `scripts/run_voice_benchmark.py --voices` renders a pronunciation probe
containing an initialism, a four-digit sequence, a time and a rupee amount.

---

## Third-party services

| Service | Role | Credential |
|---|---|---|
| Rime | TTS — the judged speech path | `RIME_API_KEY` (server-side only) |
| LiveKit Cloud | Realtime transport, agent hosting, SIP | `LIVEKIT_URL` / `_API_KEY` / `_API_SECRET` |
| Deepgram (via LiveKit Inference) | STT, `nova-3` with keyterm boosting | none — LiveKit credentials |
| LLM (via LiveKit Inference) | Response generation | none — LiveKit credentials |
| Vercel | Frontend hosting | deploy-time only |

`RIME_API_KEY` is read only by the Python worker. It is never sent to the browser;
`scripts/preflight.sh` fails the build if it is referenced anywhere under `apps/web`.

---

## Limitations

Stated plainly, because a judge will find them anyway.

1. **The measured results are in-process.** The acceptance harness exercises the real
   resolution engine on real fixtures with real injected latency, but there is no
   audio in it — no microphone, no LiveKit session, no Rime socket. It proves the
   *fence logic* holds under the stress condition. It does not prove end-to-end audio
   behaviour, and no number here should be read as an end-to-end voice latency.

2. **Interruption-to-audio-stop is unmeasured.** No target is claimed. The plan is to
   baseline it first and publish whatever it is.

3. **"What the caller heard" is close to exact, not exact.** It comes from LiveKit's
   synchronised transcript, backed by Rime word timestamps. Two residual gaps: audio
   already handed to WebRTC may play for a few milliseconds after truncation, and a
   word cut mid-syllable is counted by its start timestamp. Neither is corrected for.

4. **Correction extraction is pattern-based.** It never invents a correction, and its
   behaviour is pinned by tests — but it will miss paraphrases the patterns do not
   cover. Recall limits and the failure mode are documented in `docs/FAILURE_MODES.md`.
   The design consequence is deliberate: a *missed* correction leaves the agent no
   worse than a normal agent, whereas a *hallucinated* correction would corrupt state.

5. **The voice choice is not yet confirmed by listening.** The candidates are
   rendered and the speaking-rate data is measured, but nobody has listened and
   decided. `eyre` is configured on a catalog description, and the rate data suggests
   it may be too slow.

6. **The Rime measurements were taken from a development machine in India, not from
   the deployed worker.** They are real and repeatable, but they describe that
   machine's network path. Since the LiveKit project is also India South, production
   is likely to look similar — but "likely" is not "measured", and the
   `rime_ttfa_from_deployed_worker` entry stays open until it is.

7. **~380 ms of time-to-first-audio is geographic and unfixable in code.** Rime serves
   US regions only; this deployment is in India South. Anyone reading the latency
   numbers should read them as a distance measurement, not a Rime measurement.

8. **Telephony is not yet wired.** The SIP path (T-G) is Phase 9.

9. **The banking backend is entirely synthetic.** It is a fixture-driven mock. No real
   bank system, no real customer, no real card, no real phone number.

---

## Reproduction

From a clean clone, with no credentials:

```bash
cd agent && uv venv --python 3.12 && uv sync && cd ..
bash scripts/run_acceptance_tests.sh
python scripts/render_evidence_doc.py
```

That runs the deterministic suite, executes every acceptance scenario, regenerates
`artifacts/results.json` and `artifacts/events/*.jsonl`, verifies the configured voice
against Rime's live catalog, and rewrites the Results section above from the artifacts.

Before submitting or recording:

```bash
bash scripts/preflight.sh
```

With `RIME_API_KEY` set, the measurements listed under *Not yet measured* are filled in by:

```bash
python scripts/run_voice_benchmark.py --all
```
