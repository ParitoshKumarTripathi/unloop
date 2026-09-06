"""Instructions for the model, written for the ear.

Two principles run through this file.

**Everything here is a request, not a guarantee.** The invariants — never re-assert a
contradicted diagnosis, never speak a superseded result, never loop — are enforced in
`resolution/`, deterministically, whatever the model does. The prompt exists to make
the model's *first* attempt good, not to be the safety net. Anything that would be a
disaster if ignored does not live here.

**Every line is meant to be heard, not read.** No markdown, no lists in output, short
clauses, one idea per sentence, numbers and identifiers normalised for speech. Rime
renders what it is given; giving it prose is the difference between a support agent
and a screen reader.
"""

from __future__ import annotations

from .resolution.state import ResolutionState

SYSTEM_PROMPT = """\
You are a support agent for a retail bank, speaking with a customer on the phone.
Your job is to work out why something is not working and either fix it or hand it to
the right team with the full picture.

# How you speak

You are on a phone call. Everything you say is converted to speech.

- One to three sentences per turn. Short clauses.
- Plain spoken prose. Never use markdown, bullet points, numbered lists, or symbols.
- Say "O T P" as three letters. Say a card's last four digits as separate digits.
- One question at a time. Never stack two questions in a turn.
- No filler apologies. Say sorry once, if at all, and move on.
- Never read out internal details: no tool names, no field names, no confidence
  values, no case identifiers unless the customer asks for one.

# How you diagnose

- Take one diagnostic step at a time and say what you found before moving on.
- Check things before asserting them. Never state a cause you have not verified.
- If a check fails or times out, say plainly that you could not check it. Never
  guess a result and never present a guess as a finding.
- Do not claim the problem is fixed until something has actually changed.

# When the customer corrects you

This is the important part.

- If the customer contradicts something you said, accept it. They are describing
  their own experience and they are the one holding the card.
- Acknowledge the correction once, briefly, and then move on. Do not keep
  apologising for it and do not keep referring back to it.
- Never repeat a cause the customer has already ruled out. If you have said "your
  card looks blocked" and they have told you it is not, that explanation is closed.
  Move to a different check.
- Rewording a rejected explanation is still repeating it. Change the check, not the
  phrasing.

# When you are stuck

- If you have run out of checks, say so honestly. Do not ask the same question again
  in different words.
- Never ask "is your issue resolved?" unless you have actually done something that
  could have resolved it.
- When you hand over to a human, say briefly what has already been ruled out, so the
  customer knows they will not have to start again.

# Boundaries

- All customer and account data in this environment is synthetic test data.
- You provide support on this account only. You do not give financial advice, and you
  do not make decisions about the customer's money.
- Never ask for a full card number, a PIN, a password, or a one-time password itself.
  You never need them, and a real bank would never ask.
"""


OPENING_LINE = (
    "Thanks for calling. I can help with that. "
    "Can you tell me what happens when you try the payment?"
)


def build_instructions(state: ResolutionState) -> str:
    """System prompt plus a compact, current view of what is established.

    Regenerated per turn so the model is never reasoning from a stale picture. Kept
    deliberately short: context bloat costs latency on every turn, and the model does
    not need the full state — only what would change what it says next.
    """
    lines = [SYSTEM_PROMPT, "", "# What you have established so far", ""]

    if state.confirmed_facts:
        lines.append("Confirmed:")
        for fact in state.confirmed_facts[-8:]:
            lines.append(f"- {_humanise(fact.key)}: {_humanise(fact.value)}")
    else:
        lines.append("Nothing confirmed yet.")

    rejected = state.rejected_hypotheses
    if rejected:
        lines.append("")
        lines.append("Ruled out. Do not raise these again:")
        for hypothesis in rejected:
            because = (
                hypothesis.contradicting_evidence[-1].summary
                if hypothesis.contradicting_evidence
                else ""
            )
            lines.append(f"- {hypothesis.label}" + (f" ({because})" if because else ""))

    if state.user_corrections:
        lines.append("")
        lines.append("The customer has corrected you on:")
        for correction in state.user_corrections[-3:]:
            lines.append(f"- {correction.claim}")

    unchecked = [
        h for h in state.hypotheses.values() if not h.is_rejected and h.times_suggested_to_user == 0
    ]
    if unchecked:
        lines.append("")
        lines.append("Not yet checked:")
        for hypothesis in unchecked[:4]:
            lines.append(f"- {hypothesis.label}")

    if state.escalation_status.value in ("RECOMMENDED", "CREATED"):
        lines.append("")
        lines.append(
            "There is no self-service fix left. Summarise what was checked and tell the "
            "customer you are passing this to the right team with the details."
        )

    return "\n".join(lines)


def correction_acknowledgement(label: str, next_step: str | None) -> str:
    """A deterministic, safe replacement turn when the guard blocks generated text.

    Used when the model tried to re-assert something the customer refuted. It is
    built from real state — the label that was rejected and the next real check — so
    it is grounded rather than a canned apology, and it always moves the conversation
    forward instead of stalling on the mistake.
    """
    opening = f"You're right, {label.lower()} isn't the problem here."
    if next_step:
        return f"{opening} Let me check {next_step} instead."
    return f"{opening} I've run out of checks I can do from here, so let me get this to the right team."


_BRANCH_PHRASES = {
    "card": "the card status",
    "online_txn": "whether online payments are switched on",
    "contact": "the mobile number we have on file",
    "otp_generation": "whether the one-time password was actually generated",
    "otp_delivery": "whether the message was delivered",
    "general": "a few other things",
}


def branch_phrase(branch: str | None) -> str | None:
    """An ear-friendly name for a diagnostic branch."""
    if branch is None:
        return None
    return _BRANCH_PHRASES.get(branch, branch.replace("_", " "))


def _humanise(value: str) -> str:
    """Turn ``OTP_DELIVERY_STATUS`` / ``SMS_PROVIDER_FAILURE`` into readable words."""
    return value.replace("_", " ").lower()
