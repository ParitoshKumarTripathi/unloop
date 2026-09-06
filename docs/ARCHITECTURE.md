# Architecture

How UNLOOP is put together, and why each boundary sits where it does.

The design record — including the API audit every decision here rests on — is
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). This document is the map.

---

## 1. The three owners

```
                     ┌─────────────────────────────────────────┐
   caller  ◀────────▶│  LiveKit   — realtime media             │
                     │  turn detection, barge-in, truncation   │
                     └───────────────┬─────────────────────────┘
                                     │ transcripts / audio frames
                     ┌───────────────▼─────────────────────────┐
                     │  UNLOOP    — belief                     │
                     │  state_version, hypotheses, corrections │
                     │  stale fence, output guard, loops       │
                     └───────────────┬─────────────────────────┘
                                     │ approved text
                     ┌───────────────▼─────────────────────────┐
                     │  Rime      — speech                     │
                     │  coda, WebSocket, word timestamps       │
                     └─────────────────────────────────────────┘
```

The split matters because it is where most voice agents go wrong. LiveKit's
interruption handling is excellent and it solves a *media* problem: when the caller
speaks, stop the audio. It does not and cannot solve the *application* problem: the
tool call issued four seconds ago is still in flight, and the response the LLM already
started generating is still queued. Those are business state. Silence is not
correctness.

## 2. Data flow for one turn

```
caller audio
   │
   ├─▶ LiveKit VAD + inference.TurnDetector ──▶ endpointing
   │
   ├─▶ deepgram/nova-3 (keyterm-boosted)  ──▶ interim + final transcript
   │
   │   on FINAL transcript, before the model sees anything:
   │      CorrectionExtractor.extract()      structured corrections
   │      CorrectionReconciler.apply()       reject hypotheses, BUMP state_version
   │      LoopDetector.assess()              strategy change or escalation
   │      Agent.update_instructions()        model sees current belief
   │
   ├─▶ LLM (preemptive generation ON)
   │      speech_created ──▶ SpeechTicket stamped with state_version
   │      function_tool  ──▶ SupportBackend.call()
   │                            └─▶ registers originating_state_version
   │                            └─▶ awaits injected delay
   │                            └─▶ StaleFence.evaluate_tool()
   │
   ├─▶ tts_node  ── per sentence ──▶ OutputGuard.check()
   │                             ──▶ StaleFence.authorize_speech()
   │                             ──▶ pass, or substitute a grounded correction
   │
   └─▶ rime.TTS (WebSocket, coda, 24 kHz) ──▶ LiveKit ──▶ caller
                    │
                    └─▶ word timestamps ──▶ transcript synchroniser
                                        ──▶ truncated "what was heard" on interrupt
```

## 3. The state model

`ResolutionState` (`resolution/state.py`) is the authoritative record. It is a plain
Python object with no model in it, so every invariant is testable without a key, a
socket or a token budget.

| Field | Purpose |
|---|---|
| `state_version` | Monotonic integer. The whole staleness mechanism. |
| `version_log` | Why each bump happened, and which **subjects** it invalidated. |
| `hypotheses` | Candidate causes with status, evidence and rejection version. |
| `user_corrections` | Structured corrections, each tied to a version boundary. |
| `confirmed_facts` | What we are willing to say out loud. |
| `pending_tools` / `completed_tools` | In-flight and returned calls, each carrying its originating version. |
| `speech_records` | Per-turn lifecycle, including what was actually **heard**. |
| `loop_score`, `current_strategy`, `escalation_status` | Where the conversation is going. |

### Why `state_version` is a single counter

One counter, but staleness is decided by **subject**, not by version distance. A
correction about the card bumps the same counter as one about the mobile number; what
distinguishes them is `VersionBump.invalidated_subjects`. A card-status result that
arrives after a *mobile* correction is old but not wrong, and is used normally.

This is the difference between a fence and a blunt instrument. Discarding everything
late would pass the headline test and be wrong — it would throw away evidence we paid
a network round-trip for, and make the agent needlessly ignorant after every
correction.

## 4. The stale fence

`resolution/stale_fence.py`. Two entry points, three verdicts.

**`evaluate_tool(result)`**

| Verdict | Condition | Consequence |
|---|---|---|
| `FRESH` | issued at the current version | fully usable |
| `RECONCILABLE` | version drifted, but no correction touched this subject | usable |
| `SUPERSEDED` | a correction after issue invalidated this subject | `stale=True`, kept as evidence, **refused speech** |

**`authorize_speech(ticket)`** — three rules in order:

1. **Rejected hypothesis.** Blocks any turn asserting a hypothesis the caller
   refuted. Applies at *any* version, including the current one — an LLM can produce a
   contradicted diagnosis in a brand-new response just as easily as in a stale one.
2. **Superseded dependency.** A turn generated before a correction that invalidated
   its subject is answering a withdrawn question, whatever its wording. This catches
   obsolete turns that name no hypothesis at all ("Let me just finish checking that").
3. **Otherwise allow.** Drift alone is not grounds to mute the agent.

## 5. The output guard

`resolution/output_guard.py`, invoked from `Agent.tts_node`.

Gating is **per sentence**, not per response. Buffering a whole response to check it
would add its full generation time to time-to-first-audio, which on a phone call is
the difference between responsive and broken. A clean first sentence starts
synthesising while the second is still arriving.

Assertion detection is regex plus **backward-only negation**. That direction is the
whole trick:

- `"your card is blocked"` → assertion → blocked once rejected.
- `"your card is **not** blocked"` → denial → allowed, because the agent must be able
  to tell the caller what it ruled out.
- `"your card is blocked, which is why the OTP **isn't** arriving"` → assertion. An
  earlier implementation looked forward for negation cues and read this as a denial,
  letting the contradicted diagnosis straight through. That case is now a regression
  test.

The guard also blocks unearned "is your issue resolved?", markdown reaching TTS, and
mentions of internal machinery.

**Why not ask a model?** A model asked "does this repeat a rejected diagnosis?" is
another chance to make the very error being guarded against, and its failures
correlate with the generator's. A regex either matches or it does not, and its
behaviour is pinned by tests.

## 6. The loop detector

`resolution/loop_detector.py`. Deterministic signals, weighted:

| Signal | Weight | Fires when |
|---|---|---|
| `REJECTED_HYPOTHESIS_REPROPOSED` | 5 | the guard had to block a repeat, or one reached the caller |
| `DIAGNOSIS_REPEATED_WITHOUT_EVIDENCE` | 3 | same normalised diagnosis twice, nothing learned between |
| `REPEATED_INEFFECTIVE_REPORTS` | 3 | the caller said "that didn't work" twice |
| `ACTION_REPEATED_WITHOUT_EVIDENCE` | 2 | same recommended action twice, nothing learned between |
| `NO_PROGRESS` | 2 | three turns with no new fact or usable result |

Score ≥ 3 triggers. `next_branch()` then returns an unexhausted diagnostic branch, or
`None` — which is the honest trigger for escalation.

Two details that matter:

- **Repetition is measured on what was *heard*.** A turn generated and blocked never
  reached the caller, so it is not a repetition from their side. It is still counted
  as a *generator* loop signal, which is a different thing.
- **Stale results do not count as evidence.** Otherwise a slow tool returning could
  reset the stagnation counter and mask a loop.

`normalise_diagnosis` strips hedges, auxiliaries and politeness, then sorts and
deduplicates tokens, so "So it looks like your card might be blocked" and "I think the
card is blocked" both reduce to `"blocked card"`. Rewording is still repeating.

## 7. What the caller actually heard

Two independent sources, both real:

1. **LiveKit's truncation.** On interruption, `agent_activity.py` replaces the
   assistant message with `playback_ev.synchronized_transcript`, or empties it if no
   frame of the agent's own audio played. That truncated text *is* the SDK's model of
   what was audible.
2. **Rime's word timestamps.** `use_websocket=True` gives
   `aligned_transcript=True`; with `use_tts_aligned_transcript=True` on the session,
   the synchroniser advances on real word annotations rather than an estimated
   speaking rate.

So the truncation point is measured, not modelled. Residual approximation — buffered
audio playing on for a few milliseconds, a word cut mid-syllable — is documented in
[FAILURE_MODES.md](FAILURE_MODES.md) rather than smoothed over.

This is the strongest reason UNLOOP uses Rime over its WebSocket path specifically,
beyond voice quality.

## 8. Preemptive generation, kept on deliberately

`preemptive_generation.enabled` defaults to `True` in livekit-agents 1.8.0: the LLM
starts generating before the turn is confirmed. It is a latency win, and it is exactly
the condition that manufactures obsolete responses.

It stays on. Turning it off would make the headline test easier to pass by removing
the hard part of the problem rather than solving it. Every response is stamped at
`speech_created` with the version it was born under, and re-checked sentence by
sentence immediately before synthesis.

## 9. Tools

`tools/banking.py`. Every call goes through `SupportBackend.call()`, which registers
the call **before** awaiting — so `originating_state_version` is the version that was
current when we decided to ask, not whatever it becomes by the time the result lands.

Subjects (`tools/types.py`) are what the fence keys on, not tool names, so a new
card-related tool is fenced correctly without touching the fence.

Latency is injectable per tool (`LatencyTable`), clamped to 15 s. The demo panel can
set it; it cannot change what a tool *returns*.

## 10. Observability

`observability/events.py`. Append-only, thread-safe, monotonic `seq` (wall-clock
timestamps tie at millisecond resolution and ordering assertions need better).

Every event carries `timestamp`, `session_id`, `state_version`, `event_type` and
non-sensitive metadata. Metadata passes through a redactor that scrubs
credential-shaped and phone-number-shaped values, so a leak needs two independent
mistakes.

The event log is the evidence trail: acceptance tests assert on it, the debug UI
renders it, and `artifacts/events/*.jsonl` is written from it.

## 11. Testing

`harness.py` is the single scenario runner used by **both** pytest and the evidence
generator. If the evidence script had its own copy, published numbers could describe
something the tests never checked.

- **Deterministic assertions** carry every invariant. No model, no network.
- **LLM judges** (`livekit.agents.evals`: accuracy, coherence, conciseness, handoff,
  relevancy, task completion, tool use, safety) grade tone and completeness only, and
  are never the sole evidence for an invariant.
- **Unmeasured is `null`.** Anything needing live audio is recorded with
  `"measured": false` and a reason, never estimated.

## 12. Deployment

| Component | Where | Notes |
|---|---|---|
| Agent worker | LiveKit Cloud | `agent/Dockerfile`, Python 3.12, `uv sync --locked` |
| Frontend | Vercel | Next.js, adapted from `agent-starter-react` |
| Telephony | LiveKit SIP | inbound trunk → dispatch rule → room per caller |
| Secrets | LiveKit secret management | `RIME_API_KEY` never leaves the worker |

The Docker build must run from the repository root — the image needs `fixtures/` as
well as `agent/`.
