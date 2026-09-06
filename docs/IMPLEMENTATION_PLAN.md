# UNLOOP — Implementation Plan (Phase 0 output)

**Status:** Phase 0 complete (documentation audit). Written before any application code.
**Date of audit:** 2026-09-06
**Working name:** UNLOOP — "Customer support that knows when it's wrong."

Everything in Section 1 was verified against live sources on the audit date: PyPI JSON
metadata, the shipped wheel source of `livekit-agents` and `livekit-plugins-rime`, the
Rime documentation site, and the Rime public voice catalog. Nothing in this document is
recalled from model memory. Where a documentation page and the shipped source disagree,
**the shipped source wins** and the disagreement is recorded.

---

## 1. Documentation audit — verified findings

### 1.1 Package versions (from PyPI JSON, 2026-09-06)

| Package | Version | Requires-Python |
|---|---|---|
| `livekit-agents` | 1.8.0 | `>=3.10,<3.15` |
| `livekit-plugins-rime` | 1.8.0 | `>=3.10` |
| `livekit-plugins-deepgram` | 1.8.0 | `>=3.10` |
| `livekit-plugins-silero` | 1.8.0 | `>=3.10` |
| `livekit-plugins-turn-detector` | 1.8.0 | `>=3.10` |
| `livekit-api` | 1.2.1 | `>=3.9` |
| `livekit` (rtc SDK) | 1.1.17 | `>=3.9` |

`livekit-plugins-rime==1.8.0` declares `Requires-Dist: livekit-agents[codecs]>=1.8.0`.

### 1.2 Rime plugin — read from the shipped wheel, not from docs

Source of truth: `livekit_plugins_rime-1.8.0-py3-none-any.whl`,
`livekit/plugins/rime/{models,tts}.py`.

**Model catalog accepted by the plugin's type:**

```python
TTSModels = Literal["mistv2", "mistv3", "coda"]
```

`arcana` is explicitly rejected at runtime with a warning:
`Rime Arcana is no longer supported. Use model="coda" instead.`
The LiveKit integration page independently records Arcana as **retired 2026-08-19**.
Any tutorial or blog post that still shows `model="arcana"` is stale.

**Defaults inside the plugin:**

- `model` unset -> `"coda"`; `speaker` unset with model unset -> `"astra"`.
- `DefaultCodaVoice = "lyra"`, `DefaultMistVoice = "cove"`.
- `sample_rate: int = 22050` (constructor default).
- `segment` unset -> `"bySentence"`.
- `lang: str = "eng"`; `TTSLangs = Literal["eng","spa","fra","ger","hin"]`.

**Endpoint constants in the plugin:**

```python
RIME_BASE_URL     = "https://users.rime.ai/v1/rime-tts"   # HTTP one-shot
RIME_WS_BASE_URL  = "wss://users-ws.rime.ai"              # WebSocket base
```

**CRITICAL — the `/ws3` double-path hazard is real and confirmed.** The plugin builds
its own path:

```python
def _ws_url(self) -> str:
    params = {"speaker": ..., "modelId": ..., "audioFormat": "pcm",
              "samplingRate": self._sample_rate, "segment": self._segment, ...}
    return f"{self._base_url}/ws3?{urlencode(encoded)}"
```

So `base_url` **must be the origin only**. Passing the full documented endpoint
`wss://users-ws.rime.ai/ws3` yields `wss://users-ws.rime.ai/ws3/ws3?...` and fails.
Rime's own docs quote the `/ws3` form because they document the raw API, not the plugin.
UNLOOP therefore stores the origin in `RIME_BASE_URL` and records the resolved endpoint
separately in `artifacts/rime_config.json`.

**Regional endpoints** (Rime docs -> *Quickstart -> Regional endpoints*, verified):

| Purpose | Endpoint | Region |
|---|---|---|
| HTTP default alias | `https://users.rime.ai` | US West (alias of `users-west`) |
| HTTP US West | `https://users-west.rime.ai` | `us-west-2` |
| HTTP US East | `https://users-east.rime.ai` | `us-east-1` |
| **WS US West** | `wss://users-ws.rime.ai` (+ `/ws3`) | `us-west-2` |
| **WS US East** | `wss://users-east-ws.rime.ai` (+ `/ws3`) | `us-east-1` |

The plugin default (`wss://users-ws.rime.ai`) is **US West**. There is no auto-routing;
region is chosen entirely by `base_url`. We benchmark both from the deployment region
rather than assuming (Section 5, `run_voice_benchmark.py`).

**WebSocket protocol as the plugin speaks it:** query params `speaker`, `modelId`,
`audioFormat=pcm`, `samplingRate`, `segment`; auth via `Authorization: Bearer <key>`;
send `{"text": ..., "contextId": ...}` then `{"operation":"flush","contextId":...}`;
receive `type` in `chunk` (base64 PCM) / `timestamps` / `done` / `error`; close with
`{"operation":"eos"}`.

**Word-level timestamps.** With `use_websocket=True` the plugin sets
`TTSCapabilities(streaming=True, aligned_transcript=True)` and forwards Rime's
`timestamps` frames as `TimedString(text, start_time, end_time)`. This is load-bearing
for UNLOOP — see ADR-006.

**Documentation vs. source discrepancy (recorded deliberately):** the LiveKit Rime
integration page states a default sample rate of `16000`; the shipped constructor
default is `22050`. We do not rely on either default — `RIME_SAMPLE_RATE` is set
explicitly and recorded in the evidence artifact.

**Rime segmentation values:** `"bySentence"` (default), `"immediate"`, `"never"`.
Native model rates per Rime's latency page: **24 kHz for Coda, 22.05 kHz for Mist**;
telephony should "request 8 kHz audio directly" rather than resampling downstream.
Rime accepts any positive integer `samplingRate`.

### 1.3 Rime voice catalog — machine-readable, public, unauthenticated

- `GET https://users.rime.ai/data/voices/all-v2.json` -> `{modelId: {lang: [speaker, ...]}}`
- `GET https://users.rime.ai/data/voices/voice_details.json` -> 863 records with
  `speaker, gender, age, country, dialect, demographic, genre, modelId, lang,
  language, description, styles, flagship`

Both returned HTTP 200 without an API key on the audit date. **This means the
"verify the current production catalog" requirement can be automated** rather than
eyeballed — `scripts/verify_rime_catalog.py` asserts our configured
`(model, speaker, lang)` triple exists in the live catalog and fails the build if not.

Coda English catalog: 162 speakers. Country spread: US 138, AU 6, GB 6, **IN 3**,
IE 3, SG 2, CA 1, NG 1, ZA 1, DO 1.

Support-voice shortlist (Coda, `eng`, flagship, professional/calm styles):

| Speaker | Gender / Age | Styles | Catalog description |
|---|---|---|---|
| `eyre` | Female / Adult | professional, formal, casual, energetic | "A warm, friendly American voice, calm and easy to listen to." |
| `lintel` | Female / Young Adult | professional, formal, energetic | "A warm young American voice, both polished and lively." |
| `bancroft` | Male / Elder | professional, formal | "A composed American voice, strong on professional and formal contexts." |
| `cupola` | Male / Adult | professional, formal, energetic | "A confident, energetic American voice, professional with warmth." |

**Provisional pick: `eyre`** — a bank-support line wants calm and legible, not upbeat.
This is a *documented provisional choice pending an actual listening test*, which
requires `RIME_API_KEY`. It is not yet an evidence-backed decision and is labelled as
such in `RIME_EVIDENCE.md` until the listening test runs.

Note on the three `country: "IN"` Coda voices (`celer`, `hawa`, `leni`): their catalog
metadata is unreliable — `hawa` is tagged `country: IN` but described as "An easygoing
American female voice", and `celer`/`leni` have empty descriptions and dialects. We do
not select a voice on this metadata alone.

### 1.4 LiveKit Agents 1.8.0 — read from the shipped wheel

**The turn/interruption API changed.** In 1.8.0 every one of
`min_endpointing_delay`, `max_endpointing_delay`, `false_interruption_timeout`,
`resume_false_interruption`, `allow_interruptions`, `discard_audio_if_uninterruptible`,
`min_interruption_duration`, `min_interruption_words`, `preemptive_generation`,
`turn_detection`, `agent_false_interruption_timeout` is decorated
`@deprecate_params(..., target_version="v2.0")` in favour of a single
`turn_handling=TurnHandlingOptions(...)`. Writing the old flat kwargs would be
writing against a deprecated surface. Verified `TypedDict` shape:

```python
TurnHandlingOptions(total=False):
    turn_detection: TurnDetectionMode | None
    endpointing: EndpointingOptions              # mode fixed|dynamic, min_delay .5, max_delay 3.0, alpha .9
    interruption: InterruptionOptions
    preemptive_generation: PreemptiveGenerationOptions
    user_turn_limit: UserTurnLimitOptions

InterruptionOptions(total=False):
    enabled: bool = True
    mode: Literal["adaptive","vad"]              # absent = auto-detect
    discard_audio_if_uninterruptible: bool = True
    min_duration: float = 0.5
    min_words: int = 0
    resume_false_interruption: bool = True
    false_interruption_timeout: float | None = 2.0
    backchannel_boundary: float | tuple[float,float] | None = (1.0, 1.0)
```

`backchannel_boundary` and `mode="adaptive"` are exactly the machinery Secondary Test F
(backchannel must not interrupt) exercises. Streaming turn detectors get tighter
endpointing defaults (`min_delay 0.3`, `max_delay 2.5`).

**Current entrypoint shape** (from `livekit-examples/agent-starter-python@main`,
pushed 2026-09-05): `AgentServer()` + `@server.rtc_session(agent_name=...)` +
`cli.run_app(server)`. The older `WorkerOptions(entrypoint_fnc=...)` pattern is not what
the current starter uses.

**Session events available for instrumentation** (`voice/events.py`):
`user_state_changed`, `agent_state_changed`, `user_input_transcribed`,
`user_transcription_timeout`, `conversation_item_added`, `agent_false_interruption`,
`overlapping_speech`, `function_tools_executed`, `metrics_collected`,
`session_usage_updated`, `speech_created`, `tool_execution_updated`, `error`, `close`,
`debug_message`. Agent states: `initializing|idle|listening|thinking|speaking`.

**`SpeechHandle`** exposes `id`, `scheduled`, `interrupted`, `done()`, `chat_items`,
`interrupt(force=...)`, `wait_for_playout()`, `add_done_callback(...)`. `SpeechCreatedEvent`
carries the handle plus `source: "say"|"generate_reply"` and `user_initiated`.

**What the caller actually heard — the SDK already does the hard part.** In
`voice/agent_activity.py` (~L3078) an interrupted speech has its chat-context message
replaced by `playback_ev.synchronized_transcript` (and set to `""` if no frame of the
agent's own audio was ever played), then added with `interrupted=True`. So the truncated
assistant message in the chat context *is* the SDK's model of what was audible. UNLOOP
consumes that rather than inventing a parallel estimate.

**Testing / evals modules that exist in 1.8.0:**

- `livekit.agents.testing.fake_job_context(...)` — run an agent in-process, no worker.
- `AgentSession.run(user_input=..., input_modality="text"|"audio")` -> `RunResult`, with
  `.expect` -> `RunAssert` / `EventAssert` (`is_message`, `is_function_call`,
  `contains_function_call`, `no_more_events`, ...) and `.judge(llm, intent=...)`.
- `livekit.agents.evals` ships exactly the judges the brief anticipated:
  `accuracy_judge, coherence_judge, conciseness_judge, handoff_judge, relevancy_judge,
  safety_judge, task_completion_judge, tool_use_judge`, plus `Evaluator`, `JudgeGroup`,
  `EvaluationResult`, and a `Judge` base class whose docstring explicitly supports
  **deterministic / programmatic checks that don't need an LLM** — which is where our
  stale-fence invariant goes.
- `livekit.agents.simulation` — `Scenario`/`ScenarioGroup`/`SimulationContext` with a
  `scenarios.yaml` run by `lk agent simulate`. `SimulationContext.fail()` is a **user
  veto ANDed with the simulator's LLM verdict** — a deterministic check can fail a run
  the LLM judge passed, but can never rescue one. That is the right polarity for us.

**LiveKit Inference STT models** (`inference/stt.py`): `deepgram/nova-3`,
`nova-3-medical`, `nova-2`, `nova-2-medical`, `nova-2-conversationalai`,
`nova-2-phonecall`, `deepgram/flux-general{,-en,-multi}`, `cartesia/*`, `assemblyai/*`,
`xai/stt-1`, `speechmatics/*`, `google/*`, `auto`. `DeepgramOptions` accepts
`keyterm: str | list[str]` and `keywords: list[tuple[str,float]]` — our domain-term
boost. Default inference STT sample rate 16 kHz, `pcm_s16le`.

### 1.5 What is NOT yet verified (honest gaps)

| Gap | Why | How it gets closed |
|---|---|---|
| Rime voice listening test | needs `RIME_API_KEY` | `scripts/run_voice_benchmark.py --listen` in Phase 1 |
| Rime East vs West latency from our deploy region | needs key + deployed worker | same script, `--regions` mode |
| `segment` bySentence vs immediate trade-off | needs key | same script, TTFA + interruption behaviour |
| 8 kHz telephony path end-to-end | needs SIP trunk | Phase 9 |
| Real interruption-to-audio-stop p95 | needs live session | Phase 8 baseline, then a target is set |
| `lk` CLI version/commands | not installed on this machine | Phase 10 |

**No numbers derived from these gaps appear anywhere until they are measured.**

---

## 2. Architecture Decision Records

### ADR-001 — Rime via the direct plugin, not via LiveKit Inference

LiveKit Inference can also serve Rime (`rime/coda`), which would need no `RIME_API_KEY`.
We use `livekit.plugins.rime.TTS` with our own key anyway.

*Why:* the judged claim is about Rime specifically. The direct plugin makes the provider
falsifiable — we control and can print the exact endpoint, model, speaker, sample rate
and transport, and a judge can read them off `artifacts/rime_config.json` and match them
to the WS URL in the logs. Routing through a gateway would hide all of that behind
LiveKit. It also gives us Rime's word timestamps, which ADR-006 depends on.

*Cost:* one more secret to manage. Accepted.

### ADR-002 — `coda` as the judged model

`mistv3` has the lower time-to-first-audio (Rime: ~37 ms P50) and would flatter a
latency number. We choose `coda`: it is Rime's flagship, it is the model the plugin
defaults to, and it carries the widest voice catalog for picking a credible support
voice. UNLOOP's claim is about *correctness under interruption*, not about winning a
TTFA benchmark, and inflating a latency figure by picking the fast model while claiming
flagship quality would be the wrong trade. `mistv3` is benchmarked alongside and the
comparison is published rather than hidden.

*Note:* the plugin sets a 240 s total HTTP timeout for `coda` vs 30 s for mist — a hint
that Coda's non-streaming path can be slow. We are on the streaming path, so this is
not on the critical path, but it argues against ever using Coda over one-shot HTTP.

### ADR-003 — WebSocket transport, `segment` decided by benchmark not by default

`use_websocket=True`, `base_url` = **origin only** (ADR: never include `/ws3`).
`segment` starts at `"bySentence"` and is only changed if the Phase-1 benchmark shows
`"immediate"` wins on perceived first-response time without hurting prosody. LiveKit
already feeds the plugin sentence-tokenized text, so `"immediate"` is plausible — but
that is a hypothesis to test, not a setting to assume.

### ADR-004 — Deterministic Python owns state; the LLM is a renderer

`ResolutionState` is a plain Python object with an integer `state_version`. The LLM
never holds authoritative belief. Hypothesis status transitions, correction reconciliation,
loop scoring and staleness are all pure functions over that object, unit-testable with no
network and no model. The LLM's only jobs are (a) proposing structured extractions that
the engine may accept or reject, and (b) turning engine-approved facts into a spoken
sentence. Anything the engine did not approve cannot be spoken (ADR-005).

### ADR-005 — The output guard is a hard gate, not a prompt instruction

Before any text reaches TTS it passes `OutputGuard.check(text, state)`. If the text
asserts a hypothesis whose status is `REJECTED`, the turn is blocked, an
`OUTPUT_GUARD_REJECTION` event is emitted, and a corrected turn is generated. Prompt
text like "do not repeat rejected diagnoses" is used *as well*, but is never the
mechanism — a prompt is a request, and the acceptance criterion is 0 failures in 20 runs.

### ADR-006 — "Heard" is measured from Rime word timestamps + the SDK's truncated transcript

Two independent sources, both real:

1. LiveKit's own truncation — `synchronized_transcript` written into the chat context
   with `interrupted=True` on the message.
2. Rime's `timestamps` WS frames surfaced as `TimedString`, enabled by
   `use_tts_aligned_transcript=True` on the session with `use_websocket=True`.

With (2) the synchronizer advances on **real word annotations** rather than an estimated
speaking rate, so the truncation point is measured, not modelled. We record which source
backed each turn. Where a boundary is still an approximation (the last partially-uttered
word, network buffer already handed to WebRTC), `RIME_EVIDENCE.md` says so in those words.

*This is also the cleanest answer to "why Rime specifically" beyond voice quality.*

### ADR-007 — Preemptive generation stays ON, and is treated as a stale-fence adversary

`preemptive_generation.enabled` defaults to `True` in 1.8.0: the LLM starts generating
before the turn is confirmed. That is a latency win and it is also precisely the
condition that manufactures obsolete responses. We keep it on and make the fence handle
it, because turning it off would be quietly removing the hard part of the problem.
Every generated response carries the `state_version` it was born under; a response born
under version *n* cannot be spoken once state is at *n+1*.

### ADR-008 — STT via LiveKit Inference `deepgram/nova-3` with keyterm boosting

One credential instead of two, and `keyterm` gives us the domain-term boost the brief
asks for. `nova-2-phonecall` is benchmarked for the SIP path in Phase 9 rather than
assumed better. English only in MVP; multilingual explicitly out of scope.

### ADR-009 — Fixtures are files, delays are fixture-driven, demo controls set fixtures only

`set_mock_tool_delay` mutates a fixture-backed latency table. The demo UI can pick a
scenario and a delay; it cannot script the conversation, fake a transcript, or force a
hypothesis. Anything the judge sees on screen is a consequence of the real engine
running on the real fixture.

### ADR-010 — Python 3.12 locally

`livekit-agents` requires `>=3.10,<3.15`. Local Python is 3.12.10 (3.13.14 also present).
We pin 3.12 for the venv; the starter's Dockerfile builds on `uv:python3.14-bookworm-slim`
and we will adjust that image only if a dependency fails to resolve there.

---

## 3. Dependency / version plan

**Agent (`agent/pyproject.toml`)** — `requires-python = ">=3.10,<3.15"`

```
livekit-agents[codecs]>=1.8.0,<2      # deprecations target v2.0; cap the major
livekit-plugins-rime>=1.8.0,<2        # the judged TTS path
livekit-plugins-silero>=1.8.0,<2      # VAD
livekit-plugins-turn-detector>=1.8.0,<2
pydantic>=2                           # typed ToolResult / state models
python-dotenv
```

dev: `pytest`, `pytest-asyncio`, `ruff`

Lockfile: `uv.lock`, committed (the starter's Dockerfile runs `uv sync --locked`).
Carry over the starter's `constraint-dependencies = ["yarl<1.24"]` workaround.

**Web (`apps/web`)** — fork of `livekit-examples/agent-starter-react@main` (Next.js +
React + TS + Tailwind + shadcn, pnpm-locked, 934 stars, last push 2026-09-04). We keep
`components/agents-ui/*`, `components/ui/*`, `app/api/token/route.ts` and the session
provider, and add our debug panel around them. `pnpm` is not installed locally — install
via `corepack enable` at Phase 7.

## 4. Repository bootstrap commands

Already executed for the skeleton:

```bash
mkdir -p unloop && cd unloop && git init -b main
mkdir -p agent/src/unloop/{resolution,tools,observability,fixtures} \
         agent/tests apps fixtures scripts artifacts/events docs
python -m pip install --upgrade uv          # uv 0.12.10
```

Phase 1:

```bash
cd agent && uv venv --python 3.12 && uv sync
```

Phase 7 (frontend):

```bash
cd apps && git clone --depth 1 https://github.com/livekit-examples/agent-starter-react web
rm -rf web/.git && corepack enable && cd web && pnpm install
```

## 5. Proposed file structure

```
unloop/
├── agent/
│   ├── src/unloop/
│   │   ├── agent.py              AgentServer + rtc_session entrypoint
│   │   ├── config.py             env -> typed config; Rime config record
│   │   ├── prompts.py            written-for-the-ear system prompt
│   │   ├── resolution/
│   │   │   ├── state.py          ResolutionState, state_version, event timeline
│   │   │   ├── hypotheses.py     Hypothesis + status transitions
│   │   │   ├── corrections.py    correction extraction + reconciliation
│   │   │   ├── loop_detector.py  deterministic loop signals
│   │   │   ├── stale_fence.py    version fence for tools and speech
│   │   │   └── output_guard.py   pre-TTS rejected-hypothesis gate
│   │   ├── tools/{banking,escalation,latency}.py
│   │   ├── observability/{events,metrics}.py
│   │   └── fixtures/loader.py
│   ├── tests/                    deterministic pytest + LiveKit RunResult evals
│   ├── pyproject.toml  uv.lock  Dockerfile
├── apps/web/                     adapted agent-starter-react
├── fixtures/                     otp_{normal,correction,slow_tool,escalation}.json
├── scripts/                      preflight, acceptance, benchmark, evidence, catalog verify
├── artifacts/                    rime_config.json, results.json, events/*.jsonl
├── docs/                         IMPLEMENTATION_PLAN, ARCHITECTURE, DEMO_SCRIPT, FAILURE_MODES
├── README.md  RIME_EVIDENCE.md  .env.example  .gitignore  Taskfile.yaml
```

## 6. MVP acceptance tests — defined before implementation

Written now so the implementation cannot be tuned to fit a result chosen later.

**T-PRIMARY — stale-result fence under interruption.**
Given the OTP fixture and `get_card_status` delayed 3000 ms; the agent is speaking a
`CARD_BLOCKED`-shaped diagnostic turn; at ~1.2 s the caller says *"No, my card is not
blocked. I used it five minutes ago. Check the OTP delivery."* Then:

1. `INTERRUPTION_DETECTED` is emitted and agent audio stops.
2. `state_version` increments exactly once for that correction.
3. `CARD_BLOCKED.status` becomes `REJECTED` with the user evidence recorded.
4. The in-flight `get_card_status` result arrives with
   `originating_state_version < current_state_version`, is marked `stale=True`, and
   **`stale_tool_result.triggered_speech is False`**.
5. No event after the rejection contains a spoken assertion of `CARD_BLOCKED`.
6. The final spoken turn addresses OTP delivery.

Targets: stale leakage 0/20; contradicted-diagnosis recurrence 0/20; final state
reflects correction 20/20; handoff packet complete 20/20. Interruption -> audio-stop p95:
**baseline first, target set afterwards** — no number is claimed here.

**T-A normal flow** — no interruption; reaches delivery-failure diagnosis; no repeated
"is your query resolved?".

**T-B contradiction** — explicit rejection + tool `ACTIVE` => `REJECTED`, evidence from
both sources.

**T-C loop** — user rejects twice with no new evidence => `LOOP_DETECTED`, strategy
changes or escalates; never the same diagnosis a third time.

**T-D tool failure** — OTP API raises/timeouts => uncertainty stated, nothing fabricated,
no hypothesis promoted on missing data.

**T-E escalation** — no path remains => handoff packet with confirmed / rejected /
corrections / attempted / recommended destination.

**T-F backchannel** — "uh-huh" mid-turn with `interruption.mode="adaptive"` and
`backchannel_boundary` => no interruption, no state-version change.

**T-G telephony** — T-PRIMARY repeated over SIP.

Deterministic assertions carry T-PRIMARY, T-B, T-C, T-F. LLM judges
(`accuracy`, `coherence`, `conciseness`, `task_completion`, `tool_use`, `handoff`) grade
tone and completeness only, and can never be the sole evidence for an invariant.

## 7. Risk list

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **No credentials yet** (`RIME_API_KEY`, LiveKit, LLM). Live voice, listening test, region benchmark, SIP all blocked. | **Blocking for live paths** | Build every deterministic layer + full test suite offline now; live paths light up the moment keys land. Flagged to the user immediately. |
| R2 | `preemptive_generation=True` manufactures obsolete replies (ADR-007) | High | The fence is designed for it; T-PRIMARY runs with it enabled. |
| R3 | Judge cannot tell a real fence from a prompt that happened to behave | High | Deterministic assertions + an artifact showing the stale result arriving, being fenced, and not speaking. |
| R4 | `/ws3` double-path misconfiguration | Medium | Already characterised; `config.py` strips a trailing `/ws3` and warns; a unit test asserts the resolved URL. |
| R5 | Chosen Coda speaker sounds wrong for bank support | Medium | Shortlist of 4 + a real listening test before submission; provisional status labelled until then. |
| R6 | SIP trunk/number unobtainable in time | Medium | Browser path is the fallback demo; SIP is Phase 9 and its absence is stated, not hidden. |
| R7 | 8 kHz telephony resampling not what we claim | Medium | Request 8 kHz from Rime directly per their guidance; document any LiveKit-side transcode. |
| R8 | Interruption p95 disappoints | Medium | It is a measurement, not a promise. Published as measured. |
| R9 | Scope creep into a general assistant | Medium | Section 6 of the brief is a hard boundary; resolution only. |
| R10 | Windows dev vs Linux container drift | Low | `uv.lock` committed; Docker build verified before submission. |
| R11 | Rime catalog changes before judging | Low | `verify_rime_catalog.py` runs in preflight against the live JSON. |
| R12 | Secret leakage into the repo or the demo video | High | `.env*` gitignored except `.env.example`; `scripts/preflight.sh` runs a secret scan; `RIME_API_KEY` never crosses into the browser bundle. |

## 8. Implementation checklist

- [x] **P0** Documentation audit; this plan; repo skeleton
- [ ] **P1** Minimal real voice loop — browser -> LiveKit -> STT -> LLM -> **direct Rime** -> browser
- [ ] **P2** Synthetic banking fixtures + deterministic tools + injectable latency
- [ ] **P3** Resolution state, hypotheses, corrections, output guard
- [ ] **P4** Interruption handling on `TurnHandlingOptions`
- [ ] **P5** **Stale-result fence** — the critical milestone
- [ ] **P6** Loop detector
- [ ] **P7** Observability + judge/debug UI on the React starter
- [ ] **P8** Acceptance suite + machine-generated artifacts
- [ ] **P9** SIP telephony; repeat T-PRIMARY over a real call
- [ ] **P10** Vercel + LiveKit Cloud deployment
- [ ] **P11** Submission hardening — README, RIME_EVIDENCE, demo script, secret scan, clean-clone test
