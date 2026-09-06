# Failure modes

What UNLOOP does when things go wrong, and — more usefully — the ways UNLOOP itself
can fail. A system that only documents its successes has not been examined.

---

## 1. Failures the system handles by design

### A tool times out or errors

The result carries `status=TIMEOUT|ERROR` and an empty payload. `run_tool` returns a
sentence instructing the model to say plainly that the check did not complete, and no
hypothesis is promoted or rejected on missing data — `_absorb` only runs on a
successful payload.

*Why it matters:* the tempting failure is to treat "could not check" as "checked and
found nothing wrong". `test_tool_failure_becomes_an_open_question_not_a_fabrication`
asserts the payload stays empty, the delivery hypothesis stays `ACTIVE`, and the
failure surfaces in the handoff packet as an open question.

### A late tool result is superseded

Marked `stale=True`, `fence_verdict=SUPERSEDED`, kept in `completed_tools` as
historical evidence, and refused speech. `TOOL_MARKED_STALE` is emitted.

*Not* discarded: it may still matter to the human who picks up the case, and throwing
away data we paid a network round-trip for would be its own bug.

### A late result is merely old

If no correction invalidated its subject, the verdict is `RECONCILABLE` and it is used
normally. An OTP delivery check does not become wrong because the caller corrected us
about the card. Discarding every late result would pass the headline test and be
wrong; `test_unrelated_subject_survives_a_correction` exists to stop that shortcut.

### The model re-proposes a rejected diagnosis

The output guard blocks the sentence before synthesis, emits
`OUTPUT_GUARD_REJECTION`, substitutes a grounded correction built from real state
("You're right, the debit card is blocked isn't the problem here. Let me check whether
the message was delivered instead."), and drops the rest of that response — speaking
the tail of an argument whose premise was just refused would be incoherent.

The attempt is also a loop signal, weighted highest (5). The guard stopping a repeat
means the *generator* is stuck, even though the caller never hears it.

### Every diagnostic branch is exhausted

`LoopDetector.next_branch()` returns `None`, escalation status becomes `RECOMMENDED`,
and the agent hands over with a structured packet. This is the honest end of the
conversation, and it is why "no branch left" is a first-class return value rather than
a fallback to asking the same questions again.

### The caller and the backend disagree

If the backend reports `card_status=BLOCKED` and the caller says it works, the
hypothesis is **still rejected** — they are holding the card — *and* a
`caller_tool_conflict` signal is recorded, surfacing in the handoff packet's
`conflicts`. Quietly deciding the customer is wrong is the exact behaviour this
product exists to eliminate; quietly discarding the backend reading would be equally
dishonest.

### The caller backchannels

`interruption.mode="adaptive"` with `backchannel_boundary` lets LiveKit distinguish
"mhm" from a real interruption. A false interruption emits `FALSE_INTERRUPTION` and
**does not** bump the state version — treating a backchannel as a correction would
fence perfectly good work.

### Rime is unreachable

The session raises. There is no fallback TTS provider, deliberately: a silent fallback
would mean the judged speech path could quietly become something other than Rime. The
failure is visible in the logs and on the provider badge.

### An invalid Rime configuration

`unloop_session` calls `config.rime.validate()` before starting and **refuses to
start** if there are problems. Starting with a broken speech path and discovering it
mid-call is worse than not starting.

---

## 2. Ways UNLOOP itself can fail

These are real. Each is stated with its consequence and what bounds it.

### Correction extraction misses a paraphrase

`CorrectionExtractor` is pattern-based. "My card is not blocked" is caught; something
like "I'd be surprised if that were the issue given how I've been using it" is not.

*Consequence:* the correction is not registered, the version does not bump, and the
hypothesis stays active. The agent then behaves like an ordinary agent — no worse, but
no better.

*Why patterns anyway:* the alternative failure is much more expensive. A model-based
extractor would catch more paraphrases and would sometimes **invent** a correction,
rejecting a hypothesis the caller never disputed and corrupting authoritative state.
Missing a correction degrades gracefully; hallucinating one does not. An LLM-proposed
extraction can be fed through `apply_extraction` as a *proposal* the deterministic
layer validates — never as an authority.

*Bounded by:* a bare "no" still works, because
`_most_recently_suggested` maps it onto the last diagnosis the caller actually heard.
So the common case survives even when the phrasing is unusual.

### The output guard's regexes miss a phrasing

`asserted_in` matches specific patterns. A sufficiently oblique re-assertion of
`CARD_BLOCKED` could slip through.

*Consequence:* the invariant is violated — a contradicted diagnosis reaches the caller.

*Bounded by:* three things. The prompt also asks the model not to (belt as well as
braces); `_spoke_rejected_hypothesis()` in the loop detector checks *heard* transcripts
for exactly this and raises a loop signal if it ever happens; and the negation logic is
regression-tested against the case that actually bit during development — a later
clause's "isn't" wrongly cancelling the assertion.

*Not bounded by:* anything that would catch a genuinely novel phrasing. This is a real
residual risk, not a solved problem.

### The guard is over-eager and blocks a legitimate sentence

The mirror risk, and the more damaging one in practice: if "your card is **not**
blocked" were read as an assertion, the agent could not tell the caller what it ruled
out, which would make it *appear* to ignore the correction — the exact symptom.

*Bounded by:* `_is_negated` looks backwards from the match only, never forwards, and
trims at clause boundaries. Six explicit denial phrasings are tested. An earlier
implementation looked forty characters *forward* and did exhibit this bug; the
regression cases are in `test_output_guard.py`.

### Preemptive generation outruns the fence

`preemptive_generation` is on (ADR-007), so the LLM starts generating before the turn
is confirmed. A response can be well underway when the correction lands.

*Bounded by:* every response is stamped at `speech_created` with the version it was
born under, and `tts_node` re-checks each sentence against *current* state
immediately before synthesis. The window between the guard passing a sentence and that
audio reaching the caller's ear is not zero, but it is milliseconds, and LiveKit
truncates playback on interruption within it.

### Sentence-level gating splits an unusual sentence wrongly

`_split_sentence` breaks on `.!?` followed by whitespace or end-of-buffer. An
abbreviation ("Rs. 2,499") would split early.

*Consequence:* a fragment is checked and synthesised on its own. The guard still runs
on every fragment, so the invariant holds; the cost is prosody, not correctness.

### The loop detector fires on legitimate repetition

Restating a diagnosis after learning something new is good support behaviour, not a
loop.

*Bounded by:* every repetition rule requires *no new evidence in between*, measured by
counting usable tool results and confirmed facts.
`test_new_evidence_between_repeats_is_not_a_loop` pins this. Stale results
deliberately do not count as evidence — otherwise a slow tool returning could mask a
loop by resetting the counter.

### "What the caller heard" is approximate at the boundary

Derived from LiveKit's synchronised transcript, backed by Rime word timestamps. Two
residual gaps: audio already handed to WebRTC may play for a few milliseconds after
truncation, and a word cut mid-syllable is counted by its start timestamp.

*Consequence:* at the margin, a word the caller half-heard may be recorded as heard, or
one they barely caught as not heard. Neither is corrected for, and this is stated in
`RIME_EVIDENCE.md` rather than smoothed over.

### The state version is a single global counter

A correction about the card bumps the same counter as a correction about the mobile
number. Staleness is then decided by *subject*, not by version alone.

*Consequence:* if `Subject` mapping is wrong for a new tool, that tool is fenced
incorrectly — too aggressively or not aggressively enough.

*Bounded by:* `TOOL_SUBJECTS` and `_HYPOTHESIS_SUBJECTS` are small, explicit tables.
Adding a tool without adding its subject defaults to `Subject.CASE`, which is
conservative (rarely invalidated) — so the failure direction is "not fenced" rather
than "wrongly fenced". That is the wrong direction for safety, and is the first thing
to check when adding a tool.

### The harness does not exercise audio

The acceptance suite has no microphone, no LiveKit session and no Rime socket. It
proves the fence logic under the stress condition. It does not prove that LiveKit
truncates playback when it should, or that Rime's stream stops when the buffer is
cleared.

*Consequence:* a regression in the *audio* path would not be caught by a green suite.

*Mitigation:* T-F (backchannel) and T-G (telephony) are defined and unrun; live-audio
measurements are recorded as `null` in `results.json` rather than estimated, so a
reader can see exactly which half of the system has been measured.

---

## 2b. Known upstream issues

### `Tried to add a track for a participant, that's not present`

Seen in the browser console during connection on `livekit-client` 2.17.2 (the version
the starter pinned).

*Cause:* WebRTC fires `ontrack` as soon as `setRemoteDescription` is called on the
offer, before ICE connectivity exists, so `livekit-client` defers those callbacks until
the room reaches `Connected`. In 2.17.2 a deferred callback could still fire after the
subscription had already failed, by which point the participant was gone — and the
`MediaStream` id then carries no `participantSid|streamId` packing, so
`unpackStreamId` hands `onTrackAdded` a bare UUID that matches nothing. The library
logs it at `error` level.

*Not our code.* UNLOOP never adds, removes or subscribes to tracks; the panel only
reads a data channel.

*Fixed by* upgrading to `livekit-client` 2.22.2, which added `pendingTrackAddedCallbacks`
so deferred callbacks are cancelled when a subscription fails
([client-sdk-js#2019](https://github.com/livekit/client-sdk-js/pull/2019), released in
2.22.0). `apps/web/package.json` now declares `^2.22.2` rather than the starter's
`^2.17.2`, so a fresh clone cannot resolve back below the fix.

That release train also carries a data-channel close race fix (2.20.0), which matters
here because the resolution panel is driven entirely over the data channel.

---

## 3. Things deliberately not built

- **No fallback TTS provider.** Silent failover would make the judged path unverifiable.
- **No LLM judge on the core invariant.** A model asked whether it repeated itself is
  correlated with the error being checked. LLM judges grade tone only.
- **No automatic un-rejection from tool evidence.** `add_support` on a rejected
  hypothesis records the tension and refuses to flip the status. Only
  `reactivate()` can, and only with evidence observed *after* the rejection.
- **No multilingual support in the MVP.** `deepgram/nova-3` in English. Hindi and
  code-switching are out of scope, not partially done.
- **No conversational scripting in the demo controls.** They set fixture conditions
  only — which scenario, and how slow a tool is. Nothing can fake a transcript, force
  a hypothesis, or change what a tool returns.
