"""The output guard — the last thing between generated text and the caller's ear.

Everything the agent is about to say passes through :meth:`OutputGuard.check`. It
answers one question deterministically: *does this sentence assert something we have
already established is false?*

It works by regex matching plus negation detection (see
:meth:`Hypothesis.asserted_in`), not by asking a model. That distinction is the point.
A model asked "does this text repeat a rejected diagnosis?" is another chance to get
it wrong, correlated with the very mistake we are guarding against. A regex either
matches or it does not, and its behaviour is pinned by unit tests.

The guard also carries a small amount of conversational hygiene that is genuinely
rule-shaped: the repeated "is your issue resolved?" that makes looping agents so
maddening is blocked here rather than requested in a prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..observability.events import EventType
from ..tools.types import Subject
from .state import ResolutionState

#: "Is your query resolved?" and friends. Blocked unless something actually changed.
_RESOLUTION_CHECK = re.compile(
    r"\b(?:is|has)\b[^.?!]{0,25}\b(?:issue|problem|query|concern|this)\b[^.?!]{0,25}"
    r"\b(?:resolved|sorted|fixed|solved|working now)\b"
    r"|\bdid\s+(?:that|it)\s+(?:work|help|fix|solve|resolve)\b"
    r"|\banything\s+else\s+(?:i\s+can\s+help|you\s+need)\b",
    re.IGNORECASE,
)

#: Markdown and list syntax that must never reach a TTS engine.
_MARKDOWN = re.compile(
    r"(?:^|\n)[ \t]*(?:[-*+][ \t]+|\d+[.)][ \t]+|#{1,6}[ \t]+)"
    r"|\*\*|__|`{1,3}|\[[^\]]+\]\([^)]+\)"
)


@dataclass
class GuardResult:
    """The verdict on one proposed utterance."""

    allowed: bool
    text: str
    asserted_hypotheses: tuple[str, ...] = ()
    depends_on: frozenset[Subject] = field(default_factory=frozenset)
    violations: tuple[str, ...] = ()
    reason: str = ""
    #: Guidance handed back to the generator when a turn is blocked, so the retry is
    #: informed rather than a re-roll of the same dice.
    regeneration_hint: str = ""


#: Which subjects a mention of each hypothesis makes the turn depend on. Used by the
#: stale fence's rule 2: a turn about the card is obsolete once a correction
#: invalidates the card subject, whatever its wording.
_HYPOTHESIS_SUBJECTS: dict[str, frozenset[Subject]] = {
    "CARD_BLOCKED": frozenset({Subject.CARD}),
    "ONLINE_TXN_DISABLED": frozenset({Subject.ONLINE_TXN}),
    "MOBILE_NOT_REGISTERED": frozenset({Subject.MOBILE}),
    "OTP_NOT_GENERATED": frozenset({Subject.OTP_GENERATION}),
    "OTP_DELIVERY_FAILED": frozenset({Subject.OTP_DELIVERY}),
    "SMS_PROVIDER_INCIDENT": frozenset({Subject.OTP_DELIVERY, Subject.SERVICE_HEALTH}),
}


class OutputGuard:
    """Deterministic pre-speech gate."""

    def __init__(self, state: ResolutionState) -> None:
        self._state = state

    def analyse(self, text: str) -> tuple[tuple[str, ...], frozenset[Subject]]:
        """Which hypotheses does ``text`` assert, and what subjects does it depend on?

        Public because the response pipeline needs it to build a
        :class:`~unloop.resolution.stale_fence.SpeechTicket` at generation time,
        before the guard runs at speak time.
        """
        asserted = tuple(h.id for h in self._state.hypotheses.values() if h.asserted_in(text))
        subjects: set[Subject] = set()
        for hypothesis_id in asserted:
            subjects |= _HYPOTHESIS_SUBJECTS.get(hypothesis_id, frozenset())
        return asserted, frozenset(subjects)

    def check(self, text: str, *, speech_id: str = "") -> GuardResult:
        """Decide whether ``text`` may be spoken."""
        state = self._state
        asserted, depends_on = self.analyse(text)
        violations: list[str] = []
        hints: list[str] = []

        # --- 1. contradicted diagnosis (the invariant) ----------------------
        rejected = tuple(
            hid
            for hid in asserted
            if (h := state.get_hypothesis(hid)) is not None and h.is_rejected
        )
        if rejected:
            violations.append("REJECTED_HYPOTHESIS")
            labels = [state.hypotheses[hid].label for hid in rejected if hid in state.hypotheses]
            hints.append(
                "Do not state "
                + "; ".join(labels)
                + ". That was ruled out. Move to the next unchecked diagnostic step."
            )

        # --- 2. premature or repeated resolution check ----------------------
        if _RESOLUTION_CHECK.search(text) and not self._resolution_check_earned():
            violations.append("UNEARNED_RESOLUTION_CHECK")
            hints.append(
                "Do not ask whether the issue is resolved. Nothing has been fixed yet. "
                "Say what you found and what you are doing next."
            )

        # --- 3. formatting that a TTS engine should never receive -----------
        if _MARKDOWN.search(text):
            violations.append("MARKDOWN_IN_SPEECH")
            hints.append("Write plain spoken prose. No lists, headings, or markup.")

        # --- 4. leaking internal machinery ----------------------------------
        if re.search(
            r"(?i)\b(hypothes[ie]s|confidence score|state[_ ]version|tool call|payload)\b", text
        ):
            violations.append("INTERNAL_LEAK")
            hints.append("Do not mention internal state, tools, or confidence values.")

        if violations:
            if state is not None:
                state.recorder.emit(
                    EventType.OUTPUT_GUARD_REJECTION,
                    state_version=state.state_version,
                    speech_id=speech_id,
                    violations=violations,
                    blocked_hypotheses=list(rejected),
                    text_preview=text[:160],
                )
            return GuardResult(
                allowed=False,
                text=text,
                asserted_hypotheses=asserted,
                depends_on=depends_on,
                violations=tuple(violations),
                reason=", ".join(violations),
                regeneration_hint=" ".join(hints),
            )

        return GuardResult(
            allowed=True,
            text=text,
            asserted_hypotheses=asserted,
            depends_on=depends_on,
            reason="clean",
        )

    def _resolution_check_earned(self) -> bool:
        """Has anything happened that would make "did that work?" a fair question?

        Only two things earn it: an actual remediation action, or a materially new
        outcome such as an escalation being created. Merely having looked something
        up does not.
        """
        state = self._state
        if state.escalation_status.value in ("CREATED", "HANDED_OFF"):
            return True
        remediation = {"resend_otp", "retry_otp_delivery", "reset_online_transactions"}
        return any(action in remediation for action in state.attempted_actions)
