"""Hypotheses: what UNLOOP currently believes might be wrong, and why.

The whole product rests on one property of this module: **once a hypothesis is
REJECTED it cannot quietly come back**. Re-activation is possible, because refusing
it forever would be its own failure mode, but it requires evidence that did not exist
at rejection time and it leaves a loud event behind.

Nothing here talks to a model or the network. Every transition is a pure function of
the object plus the evidence handed to it, so the invariants are unit-testable
without a session, a key, or a socket.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HypothesisStatus(str, Enum):
    ACTIVE = "ACTIVE"  # under consideration, not yet weighed
    SUPPORTED = "SUPPORTED"  # evidence points at it
    REJECTED = "REJECTED"  # contradicted; must not be asserted to the caller
    RESOLVED = "RESOLVED"  # confirmed and acted upon


class EvidenceSource(str, Enum):
    TOOL = "TOOL"  # a backend check
    USER = "USER"  # something the caller said
    SYSTEM = "SYSTEM"  # engine-derived inference


@dataclass(frozen=True)
class Evidence:
    """A single reason to believe or disbelieve something.

    ``observed_at_version`` is what makes re-activation safe: evidence gathered
    before a rejection cannot be recycled to undo that rejection.
    """

    id: str
    source: EvidenceSource
    summary: str
    observed_at_version: int
    supports: bool
    detail: dict[str, Any] = field(default_factory=dict)
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source.value,
            "summary": self.summary,
            "observed_at_version": self.observed_at_version,
            "supports": self.supports,
            "detail": self.detail,
            "observed_at": self.observed_at,
        }


class HypothesisTransitionError(RuntimeError):
    """Raised when code tries to make an illegal status transition.

    Loud on purpose. A silent illegal transition is precisely the bug this whole
    project exists to prevent, so it must not be recoverable by accident.
    """


@dataclass
class Hypothesis:
    """One candidate explanation for the caller's problem.

    ``assertion_patterns`` / ``negation_cues`` are what let the output guard work
    deterministically. The guard does not ask a model whether a sentence claims the
    card is blocked; it matches a regex and then checks for a negation cue, so
    "your card is not blocked" is correctly read as a *denial* and allowed through
    while "it looks like your card is blocked" is caught.
    """

    id: str
    label: str
    status: HypothesisStatus = HypothesisStatus.ACTIVE
    confidence: float = 0.5
    supporting_evidence: list[Evidence] = field(default_factory=list)
    contradicting_evidence: list[Evidence] = field(default_factory=list)
    first_seen_turn: int = 0
    last_updated_turn: int = 0
    times_suggested_to_user: int = 0
    #: Set when the hypothesis is rejected; gates re-activation.
    rejected_at_version: int | None = None
    #: Which diagnostic branch this belongs to, used by the loop detector to pick a
    #: genuinely different next step rather than a rephrasing of the same one.
    branch: str = "general"
    assertion_patterns: list[re.Pattern[str]] = field(default_factory=list)
    negation_cues: list[re.Pattern[str]] = field(default_factory=list)

    # --- status transitions -------------------------------------------------

    @property
    def is_rejected(self) -> bool:
        return self.status is HypothesisStatus.REJECTED

    @property
    def is_speakable(self) -> bool:
        """Whether the agent may assert this hypothesis to the caller."""
        return self.status in (HypothesisStatus.ACTIVE, HypothesisStatus.SUPPORTED, HypothesisStatus.RESOLVED)

    def add_support(self, evidence: Evidence, *, turn: int) -> None:
        if not evidence.supports:
            raise HypothesisTransitionError(
                f"evidence {evidence.id!r} is contradicting; use add_contradiction()"
            )
        self.supporting_evidence.append(evidence)
        self.last_updated_turn = turn
        if self.status is HypothesisStatus.REJECTED:
            # Deliberately *not* an automatic un-rejection. Supporting evidence is
            # recorded so a human can see the tension, but flipping the status is
            # only ever the explicit, audited act of reactivate().
            return
        self.status = HypothesisStatus.SUPPORTED
        self.confidence = min(0.99, self.confidence + 0.25)

    def add_contradiction(self, evidence: Evidence, *, turn: int) -> None:
        if evidence.supports:
            raise HypothesisTransitionError(
                f"evidence {evidence.id!r} is supporting; use add_support()"
            )
        self.contradicting_evidence.append(evidence)
        self.last_updated_turn = turn
        self.confidence = max(0.0, self.confidence - 0.4)

    def reject(self, evidence: Evidence, *, turn: int, state_version: int) -> None:
        """Mark this hypothesis contradicted. The one-way door.

        After this, :meth:`is_speakable` is False and the output guard will block any
        sentence that asserts it.
        """
        if evidence.supports:
            raise HypothesisTransitionError(
                f"cannot reject {self.id!r} with supporting evidence {evidence.id!r}"
            )
        if evidence not in self.contradicting_evidence:
            self.contradicting_evidence.append(evidence)
        self.status = HypothesisStatus.REJECTED
        self.rejected_at_version = state_version
        self.confidence = 0.0
        self.last_updated_turn = turn

    def resolve(self, *, turn: int) -> None:
        if self.status is HypothesisStatus.REJECTED:
            raise HypothesisTransitionError(
                f"cannot resolve rejected hypothesis {self.id!r} without reactivating it first"
            )
        self.status = HypothesisStatus.RESOLVED
        self.confidence = 1.0
        self.last_updated_turn = turn

    def can_reactivate(self, evidence: Evidence) -> bool:
        """Whether ``evidence`` is genuinely new grounds to reconsider a rejection.

        Three conditions, all required:

        1. the hypothesis is actually rejected;
        2. the evidence supports it;
        3. it was observed *after* the rejection — evidence that was already on the
           table when we rejected cannot be replayed to undo the rejection.

        Condition 3 is the important one. Without it, a delayed tool result issued
        before the caller's correction could arrive afterwards and silently revive
        the diagnosis the caller just refuted, which is the exact failure UNLOOP is
        built to prevent.
        """
        if not self.is_rejected or self.rejected_at_version is None:
            return False
        if not evidence.supports:
            return False
        return evidence.observed_at_version > self.rejected_at_version

    def reactivate(self, evidence: Evidence, *, turn: int) -> None:
        if not self.can_reactivate(evidence):
            raise HypothesisTransitionError(
                f"refusing to reactivate {self.id!r}: evidence {evidence.id!r} is not new "
                f"(observed at v{evidence.observed_at_version}, rejected at v{self.rejected_at_version})"
            )
        self.supporting_evidence.append(evidence)
        self.status = HypothesisStatus.SUPPORTED
        self.rejected_at_version = None
        self.confidence = 0.55
        self.last_updated_turn = turn

    # --- text matching (used by the output guard) ---------------------------

    def asserted_in(self, text: str) -> bool:
        """Does ``text`` *assert* this hypothesis (as opposed to denying it)?

        Returns True only for a positive claim. "Your card is not blocked, so that
        is not the problem" must return False — that sentence is the agent correctly
        communicating the rejection, and blocking it would make the agent unable to
        tell the caller what it ruled out.
        """
        for pattern in self.assertion_patterns:
            match = pattern.search(text)
            if match is None:
                continue
            if self._is_negated(text, match.start(), match.end()):
                continue
            return True
        return False

    def _is_negated(self, text: str, start: int, end: int) -> bool:
        """Look for a negation cue in the clause leading up to the match.

        The window runs backwards from the end of the match and never forwards.
        Negation that cancels a claim precedes it ("the card is **not** blocked",
        "I've **ruled out** a card block"); a negative further along the sentence
        belongs to a different clause. Looking forward would read
        "your card is blocked, which is why the OTP **isn't** arriving" as a denial
        and let the contradicted diagnosis straight through — the exact failure this
        guard exists to prevent.

        The window is also trimmed at a clause boundary so an earlier clause's
        negation does not bleed across: in "your number is fine, but the card is
        blocked", "fine" must not cancel the later claim.
        """
        window_start = max(0, start - 90)
        window = text[window_start:end]
        boundary = max(
            window.rfind(";"),
            window.rfind(" but "),
            window.rfind(" however "),
            window.rfind(" though "),
        )
        if boundary != -1 and (window_start + boundary) < start:
            window = window[boundary:]
        return any(cue.search(window) for cue in self.negation_cues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status.value,
            "confidence": round(self.confidence, 3),
            "branch": self.branch,
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
            "contradicting_evidence": [e.to_dict() for e in self.contradicting_evidence],
            "first_seen_turn": self.first_seen_turn,
            "last_updated_turn": self.last_updated_turn,
            "times_suggested_to_user": self.times_suggested_to_user,
            "rejected_at_version": self.rejected_at_version,
        }


# ---------------------------------------------------------------------------
# The OTP diagnostic branch set.
#
# These are the candidate explanations for "I am not receiving the OTP for my debit
# card payment". CARD_BLOCKED is deliberately first and deliberately plausible: it is
# the diagnosis a naive agent locks onto, and the one the caller refutes.
# ---------------------------------------------------------------------------

def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_NEGATION_CUES: list[re.Pattern[str]] = [
    _rx(r"\b(not|n't|no longer|isn'?t|aren'?t|doesn'?t|don'?t|wasn'?t)\b"),
    _rx(r"\b(rule[sd]? out|ruling out|ruled out|not the (?:issue|problem|cause))\b"),
    _rx(r"\b(active|enabled|working|fine|okay|ok)\b"),
    _rx(r"\b(doesn'?t|does not|cannot|can'?t)\s+explain\b"),
    _rx(r"\bno\s+(?:card\s+)?block\b"),
]


def build_otp_hypotheses() -> list[Hypothesis]:
    """The fixed diagnostic branch set for the OTP scenario.

    Fixed, not model-generated, so the loop detector has a real space of alternatives
    to move through and the acceptance tests have stable ids to assert on.
    """
    return [
        Hypothesis(
            id="CARD_BLOCKED",
            label="The debit card is blocked or deactivated",
            branch="card",
            assertion_patterns=[
                _rx(r"\bcard\b[^.?!]{0,40}\b(?:is|appears|seems|looks|might be|may be|has been)\b[^.?!]{0,20}\b(?:blocked|frozen|deactivated|disabled|suspended|restricted)\b"),
                _rx(r"\b(?:blocked|frozen|deactivated|disabled|suspended)\b[^.?!]{0,20}\bcard\b"),
                _rx(r"\bcard\s+block\b[^.?!]{0,30}\b(?:is|explains|causing|reason|why)\b"),
            ],
            negation_cues=_NEGATION_CUES,
        ),
        Hypothesis(
            id="ONLINE_TXN_DISABLED",
            label="Online or e-commerce transactions are switched off for the card",
            branch="card",
            assertion_patterns=[
                _rx(r"\bonline\s+(?:transactions?|payments?)\b[^.?!]{0,30}\b(?:are|is|been)\b[^.?!]{0,15}\b(?:disabled|off|turned off|blocked|not enabled)\b"),
                _rx(r"\b(?:disabled|turned off)\b[^.?!]{0,20}\bonline\s+(?:transactions?|payments?)\b"),
            ],
            negation_cues=_NEGATION_CUES,
        ),
        Hypothesis(
            id="MOBILE_NOT_REGISTERED",
            label="The mobile number on file is unverified or out of date",
            branch="contact",
            assertion_patterns=[
                _rx(r"\b(?:mobile|phone)\s+number\b[^.?!]{0,40}\b(?:is|appears|seems)\b[^.?!]{0,20}\b(?:unverified|not verified|not registered|out of date|outdated|wrong|incorrect)\b"),
                _rx(r"\b(?:unverified|unregistered)\b[^.?!]{0,20}\b(?:mobile|phone)\s+number\b"),
            ],
            negation_cues=_NEGATION_CUES,
        ),
        Hypothesis(
            id="OTP_NOT_GENERATED",
            label="The bank never generated an OTP for the payment",
            branch="otp_generation",
            assertion_patterns=[
                _rx(r"\bo\.?t\.?p\.?\b[^.?!]{0,40}\b(?:was|is)\b[^.?!]{0,15}\bnever\s+(?:generated|created|issued)\b"),
                _rx(r"\bno\s+o\.?t\.?p\.?\b[^.?!]{0,25}\b(?:was\s+)?(?:generated|created|issued)\b"),
                _rx(r"\bfail(?:ed|ure)\b[^.?!]{0,25}\bgenerate\b[^.?!]{0,20}\bo\.?t\.?p\.?\b"),
            ],
            negation_cues=_NEGATION_CUES,
        ),
        Hypothesis(
            id="OTP_DELIVERY_FAILED",
            label="The OTP was generated but the SMS was never delivered",
            branch="otp_delivery",
            assertion_patterns=[
                _rx(r"\bdelivery\b[^.?!]{0,30}\bfail(?:ed|ure|ing)\b"),
                _rx(r"\bo\.?t\.?p\.?\b[^.?!]{0,50}\b(?:not|never|wasn'?t|didn'?t)\b[^.?!]{0,20}\bdeliver"),
                _rx(r"\bsms\b[^.?!]{0,30}\b(?:fail(?:ed|ure)|not delivered|never (?:arrived|reached))\b"),
            ],
            # Delivery failure is asserted with negative words by nature ("the SMS was
            # never delivered"), so the generic negation cues would misfire. Only an
            # explicit "delivery did not fail" counts as a denial here.
            negation_cues=[
                _rx(r"\bdelivery\b[^.?!]{0,20}\b(?:did\s+not|didn'?t|has\s+not|hasn'?t)\s+fail"),
                _rx(r"\b(?:was|were)\s+deliver(?:ed)\b"),
            ],
        ),
        Hypothesis(
            id="SMS_PROVIDER_INCIDENT",
            label="The SMS provider is having an outage affecting delivery",
            branch="otp_delivery",
            assertion_patterns=[
                _rx(r"\b(?:sms|messaging)\s+(?:provider|gateway|service)\b[^.?!]{0,40}\b(?:outage|incident|degraded|down|failing|problem)\b"),
                _rx(r"\b(?:outage|incident)\b[^.?!]{0,30}\b(?:sms|messaging)\s+(?:provider|gateway|service)\b"),
            ],
            negation_cues=_NEGATION_CUES,
        ),
    ]
