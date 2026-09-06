# Demo script — 4 to 5 minutes

Target: **4:30**. The hard voice engineering should dominate. Do not spend time
explaining the UI.

One rule throughout: **every number on screen must be traceable to a file in
`artifacts/`.** If it is not in an artifact, do not say it.

---

## Before recording

```bash
bash scripts/preflight.sh          # must pass with 0 failures
bash scripts/run_acceptance_tests.sh
python scripts/render_evidence_doc.py
git status                          # results.json must be from a clean tree
```

Checklist:

- [ ] Terminal font large enough to read at 720p.
- [ ] Debug panel open, **SPEECH: RIME** badge visible.
- [ ] No `.env.local` file visible anywhere on screen; no key in any terminal history.
- [ ] Tool delay control set to **3000 ms** before the stress segment.
- [ ] Audio levels checked — the interruption must be clearly audible as an interruption.

---

## 0:00 – 0:30 — The problem

**On screen:** the failing conversation, as text.

> "You call your bank. A payment failed. The agent decides your card is blocked.
> You tell it you used the card twenty minutes ago. It says the card is blocked.
> It asks if your issue is resolved. You say no. It suggests the card block again.
> Then it hands you to an IVR menu and you start over."

> "Everyone has had this call. It looks like the AI is bad at listening. It isn't a
> language problem — it's a state problem. Nothing marks the wrong diagnosis as wrong,
> nothing notices when a slow tool answers a question you already withdrew, and
> nothing counts how many times the same dead end has been proposed."

> "This is UNLOOP. It's a phone support agent built around those three things."

*Do not* say "AI hallucination". Be specific — the specificity is the pitch.

## 0:30 – 1:20 — Normal call

**On screen:** browser session, debug panel visible.

Caller: *"Hi, I'm trying to make a debit card payment but I'm not receiving the OTP."*

Let it run without interference. Point at the debug panel as it moves:

- hypotheses appearing, one per diagnostic branch
- tool timeline: card status, online transactions, registered mobile, OTP generation
- each result rejecting or supporting a hypothesis
- final: OTP generated, delivery failed at the SMS provider

> "No interruption yet. It checks one thing at a time and lands on the real cause:
> the one-time password was generated, and delivery failed."

Keep this segment tight. It is the baseline, not the point.

## 1:20 – 2:45 — The stress case *(the heart of the demo)*

**On screen:** set the tool-delay control to **3000 ms** — do this visibly.

> "Now the hard part. I'm going to make the card-status check take three seconds, and
> interrupt the agent while it's still waiting."

Start a fresh call. Let the agent say the naive diagnosis and start the card check.
**Interrupt mid-sentence** — while it is still speaking:

Caller: *"No, my card is not blocked. I used it five minutes ago. Check the OTP delivery."*

Then narrate the debug panel as it updates, in this order:

1. **Rime audio stops.** The agent stops mid-word.
2. **`state_version` 1 → 2.** One correction, one increment.
3. **`CARD_BLOCKED` → REJECTED**, with the caller's own evidence attached: *caller
   reports recent successful card use*.
4. **The delayed result lands** — three seconds after it was requested, one second
   after the correction. Watch it appear in the tool timeline marked **STALE**.
5. **It is not spoken.** Point at `triggered_speech: false`.

> "That result is real. The card really is active. But it answers a question the
> caller withdrew a second ago, so it doesn't get the microphone. It stays in the
> record as evidence — it just can't speak."

6. Let the agent continue. It acknowledges the correction once and moves to delivery.

> "And it never says 'card blocked' again. That's not the prompt asking nicely — the
> guard blocks it before synthesis. Watch."

If you can trigger a blocked repeat, show the `OUTPUT_GUARD_REJECTION` event. If not,
show it from the event log in the next segment.

## 2:45 – 3:30 — Evidence

**On screen:** the debug panel's provider block, then a terminal.

> "Everything you just saw is in the artifacts."

```bash
cat artifacts/rime_config.json
```

Point at: provider Rime, model `coda`, speaker `eyre`, transport `websocket`, the
resolved endpoint `wss://users-ws.rime.ai/ws3?...`, sample rate 24000.

> "That endpoint isn't typed into the doc. A test asks the installed plugin to build
> its own URL and compares it to what we publish, so the evidence can't drift away
> from the connection we actually open."

Then the event log for the run you just did:

```bash
grep -E "STATE_VERSION_CHANGED|HYPOTHESIS_REJECTED|TOOL_MARKED_STALE|OUTPUT_GUARD_REJECTION" \
  artifacts/events/primary_stale_fence_000.jsonl
```

> "Version change. Hypothesis rejected. Tool marked stale. Guard rejection. That's the
> whole mechanism in four lines."

Then the results:

```bash
python -c "import json;d=json.load(open('artifacts/results.json'));print(d['totals'])"
```

> "A hundred out of a hundred acceptance runs. Seventeen checks per run on the stress
> case."

**Say this out loud** — it is worth more than another green number:

> "One thing I want to be straight about: those runs are in-process. Real engine, real
> fixtures, real injected delay — but no audio in the loop. Interruption-to-audio-stop
> needs a live session to measure, so it's recorded as null in results.json with a
> reason. I'm not claiming a number I haven't measured."

## 3:30 – 4:10 — Escalation

Continue the call to the point where no automated fix remains.

> "There's no self-service fix for a provider-side delivery failure. So it escalates —
> but not with a transcript."

Show the handoff packet in the debug panel:

- **Confirmed:** card active, online payments enabled, number verified, OTP generated
- **Rejected:** card blocked — *because the caller reported recent successful card use*
- **Observed:** delivery failed, SMS provider failure
- **Attempted:** the four checks
- **Routed to:** OTP and SMS delivery support

> "The human picking this up sees what was ruled out and why. They don't re-ask about
> the card block — which is exactly what makes people give up on support calls."

## 4:10 – 4:40 — Reproducibility

Fast. Repository tour, a few seconds each:

```
docs/IMPLEMENTATION_PLAN.md    the API audit, written before any code
RIME_EVIDENCE.md               claim, method, results, limitations
docs/FAILURE_MODES.md          how this can fail, including how it can fail badly
agent/tests/                   66 deterministic tests
fixtures/                      five synthetic scenarios
artifacts/                     machine-generated evidence
```

> "The acceptance tests were written in phase zero, before the engine existed, so the
> implementation couldn't be tuned to fit a result chosen later. The results section
> of the evidence doc is generated from the artifacts by a script — it physically
> can't contain a hand-typed number."

> "From a clean clone, no credentials needed:"

```bash
bash scripts/run_acceptance_tests.sh
```

> "All the data is synthetic. There's no real bank, no real customer, no real card."

Close on the one-liner:

> **"UNLOOP: customer support that knows when it's wrong."**

---

## Things to avoid

- **Don't demo the UI.** Judges do not score chrome. Every second on layout is a second
  not spent on the fence.
- **Don't claim a latency number** that is not in `artifacts/`. Saying "we don't have
  that measurement yet" is worth more than a plausible figure.
- **Don't show a fallback provider.** There isn't one, deliberately — say so if asked.
- **Don't read the handoff packet aloud field by field.** Point at three lines.
- **Don't apologise for the in-process caveat.** State it once, plainly, and move on.
  It reads as rigour, not weakness.

## If the live demo fails on the day

Have a recorded backup of the 1:20–2:45 segment. If the live call breaks, say so and
cut to it — "the live path is down, here's the same run recorded earlier" is
recoverable. Pretending is not.

The artifacts and the test suite run with no credentials at all, so the evidence
segment (2:45–3:30) works even if every network path is dead.
