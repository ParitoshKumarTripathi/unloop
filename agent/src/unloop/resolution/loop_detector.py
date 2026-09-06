"""Deterministic loop detection.

The failure this product is named after: an agent proposes a diagnosis, the caller
says no, the agent proposes it again in slightly different words, asks "is your issue
resolved?", and eventually gives up and dumps the caller into an IVR.

Loop detection is not delegated to the LLM. A model that is stuck in a loop is, by
construction, not the right judge of whether it is stuck in a loop. Instead we count
concrete, observable things:

* how often a diagnosis was actually spoken *and heard*;
* how often the caller explicitly rejected something;
* whether any new evidence arrived between two repetitions;
* whether the recommended action changed.

Any one of the trigger rules firing means the current strategy has stopped working,
and the engine must move to a different diagnostic branch or escalate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from ..observability.events import EventType
from .state import ResolutionState


class LoopSignal(str, Enum):
    REJECTED_HYPOTHESIS_REPROPOSED = "REJECTED_HYPOTHESIS_REPROPOSED"
    """We tried to say something the caller already refuted. The most serious signal."""

    DIAGNOSIS_REPEATED_WITHOUT_EVIDENCE = "DIAGNOSIS_REPEATED_WITHOUT_EVIDENCE"
    """Same diagnosis twice with nothing new learned in between."""

    ACTION_REPEATED_WITHOUT_EVIDENCE = "ACTION_REPEATED_WITHOUT_EVIDENCE"
    """Same recommended action twice with nothing new learned in between."""

    REPEATED_INEFFECTIVE_REPORTS = "REPEATED_INEFFECTIVE_REPORTS"
    """The caller has said "that didn't work" more than once without us changing tack."""

    NO_PROGRESS = "NO_PROGRESS"
    """Several turns have passed with no new facts and no new tool evidence."""


@dataclass
class LoopAssessment:
    """The verdict for one turn."""

    signals: list[LoopSignal] = field(default_factory=list)
    score: int = 0
    triggered: bool = False
    reason: str = ""
    #: A branch we have not exhausted, if one exists. ``None`` means escalate.
    suggested_branch: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "signals": [s.value for s in self.signals],
            "score": self.score,
            "triggered": self.triggered,
            "reason": self.reason,
            "suggested_branch": self.suggested_branch,
        }


_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")

#: Words that carry no diagnostic content. Stripping them is what makes rewording
#: detectable as repetition: an agent that says "your card might be blocked" and then
#: "I think the card is blocked" has said the same thing twice, and the hedging is
#: exactly the part that differs.
_STOPWORDS: frozenset[str] = frozenset(
    # determiners and pronouns
    "a an the this that these those it its there here"
    " i you your yours my mine our ours we us me they them their"
    # copulas and auxiliaries
    " is are was were be been being am do does did doing have has had"
    " will would shall should can could may might must going gonna"
    # hedges - the part that differs when an agent reworks the same claim
    " seem seems seemed look looks looked appear appears appeared"
    " think thinks thought believe believes guess suppose"
    " so well okay ok right just really actually basically simply"
    # discourse glue and politeness
    " like about into from with for and but or then than"
    " let please sorry apologies apologise apologize"
    " sir madam thanks thank very quite some any"
    " see say saying said tell telling told".split()
)


def normalise_diagnosis(text: str) -> str:
    """Reduce a spoken diagnosis to a comparable core.

    "So it looks like your card might be blocked" and "I think the card is blocked"
    both reduce to ``"blocked card"``, which is what makes "repeated twice"
    detectable rather than defeated by paraphrase.

    Tokens are sorted and deduplicated, so word order does not matter either — an
    agent that reorders a clause has still repeated itself.
    """
    lowered = _NON_WORD.sub(" ", text.lower())
    tokens = {
        token
        for token in _SPACES.sub(" ", lowered).strip().split(" ")
        if len(token) > 2 and token not in _STOPWORDS
    }
    return " ".join(sorted(tokens))


class LoopDetector:
    """Counts repetition and decides when the strategy must change."""

    #: A hypothesis spoken to the caller this many times without resolution is a loop.
    MAX_SUGGESTIONS = 2
    #: Turns without a new fact or tool result before NO_PROGRESS fires.
    STAGNANT_TURNS = 3
    #: Score at which the engine must change strategy or escalate.
    TRIGGER_SCORE = 3

    _WEIGHTS: ClassVar[dict[LoopSignal, int]] = {
        LoopSignal.REJECTED_HYPOTHESIS_REPROPOSED: 5,
        LoopSignal.DIAGNOSIS_REPEATED_WITHOUT_EVIDENCE: 3,
        LoopSignal.ACTION_REPEATED_WITHOUT_EVIDENCE: 2,
        LoopSignal.REPEATED_INEFFECTIVE_REPORTS: 3,
        LoopSignal.NO_PROGRESS: 2,
    }

    def __init__(self, state: ResolutionState) -> None:
        self._state = state
        self._spoken_diagnoses: list[tuple[str, int, int]] = []
        """(normalised text, state_version, evidence_count_at_time)"""
        self._recommended_actions: list[tuple[str, int]] = []
        """(action, evidence_count_at_time)"""
        self._turns_without_progress = 0
        self._last_evidence_count = 0

    # -- recording -----------------------------------------------------------

    def record_spoken_diagnosis(
        self, text: str, *, hypothesis_ids: list[str] | None = None
    ) -> None:
        """Record a diagnosis the caller actually heard.

        Called from the speech-completion path. A generated-but-never-played turn is
        not a repetition, because from the caller's side it never happened.
        """
        normalised = normalise_diagnosis(text)
        if not normalised:
            return
        self._spoken_diagnoses.append(
            (normalised, self._state.state_version, self._evidence_count())
        )
        for hypothesis_id in hypothesis_ids or []:
            self._state.mark_hypothesis_suggested(hypothesis_id)

    def record_recommended_action(self, action: str) -> None:
        self._recommended_actions.append((action.strip().lower(), self._evidence_count()))

    # -- assessment ----------------------------------------------------------

    def assess(self) -> LoopAssessment:
        """Evaluate the current turn for looping."""
        state = self._state
        signals: list[LoopSignal] = []

        # 1. Did we attempt to re-propose something already refuted?
        #
        # Two independent sources, because they catch different failures:
        #   (a) the output guard blocked a re-proposal before it could be spoken —
        #       the generator tried, and this is the signal that it is stuck;
        #   (b) a rejected hypothesis nonetheless reached the caller's ears, which
        #       would mean the guard was bypassed. That must never happen, but
        #       detecting it here rather than assuming it away is the point.
        if self._guard_blocked_rejected_hypothesis() or self._spoke_rejected_hypothesis():
            signals.append(LoopSignal.REJECTED_HYPOTHESIS_REPROPOSED)

        # 2. Same diagnosis twice with no new evidence in between.
        if self._repeated_without_new_evidence(self._spoken_diagnoses_pairs()):
            signals.append(LoopSignal.DIAGNOSIS_REPEATED_WITHOUT_EVIDENCE)

        # 3. Same recommended action twice with no new evidence in between.
        if self._repeated_without_new_evidence(self._recommended_actions):
            signals.append(LoopSignal.ACTION_REPEATED_WITHOUT_EVIDENCE)

        # 4. The caller has told us twice that nothing changed.
        ineffective = [
            e
            for e in state.recorder.of_type(EventType.LOOP_SIGNAL)
            if e.meta.get("signal") == "user_reports_ineffective"
        ]
        if len(ineffective) >= 2:
            signals.append(LoopSignal.REPEATED_INEFFECTIVE_REPORTS)

        # 5. Nothing new has been learned for several turns.
        if self._turns_without_progress >= self.STAGNANT_TURNS:
            signals.append(LoopSignal.NO_PROGRESS)

        # A hypothesis suggested more than MAX_SUGGESTIONS times is a loop even if
        # each individual repetition looked justified at the time.
        over_suggested = any(
            h.times_suggested_to_user > self.MAX_SUGGESTIONS for h in state.hypotheses.values()
        )
        if over_suggested and LoopSignal.DIAGNOSIS_REPEATED_WITHOUT_EVIDENCE not in signals:
            signals.append(LoopSignal.DIAGNOSIS_REPEATED_WITHOUT_EVIDENCE)

        score = sum(self._WEIGHTS[s] for s in signals)
        triggered = score >= self.TRIGGER_SCORE
        assessment = LoopAssessment(
            signals=signals,
            score=score,
            triggered=triggered,
            reason=", ".join(s.value for s in signals) or "no loop signals",
            suggested_branch=self.next_branch() if triggered else None,
        )

        state.loop_score = score
        for signal in signals:
            state.recorder.emit(
                EventType.LOOP_SIGNAL,
                state_version=state.state_version,
                signal=signal.value,
                score=score,
            )
        if triggered:
            state.recorder.emit(
                EventType.LOOP_DETECTED,
                state_version=state.state_version,
                signals=[s.value for s in signals],
                score=score,
                suggested_branch=assessment.suggested_branch,
            )
        return assessment

    def note_turn(self) -> None:
        """Call once per completed turn to track stagnation."""
        current = self._evidence_count()
        if current > self._last_evidence_count:
            self._turns_without_progress = 0
            self._last_evidence_count = current
        else:
            self._turns_without_progress += 1

    def next_branch(self) -> str | None:
        """A diagnostic branch with an unrejected hypothesis we have not exhausted.

        ``None`` means every branch is spent, which is the honest trigger for
        escalation rather than another lap of the same questions.

        Candidates are ranked: evidence-supported hypotheses first (that is where the
        answer most likely is), then untried ones in the order they are declared,
        which is the natural diagnostic order for the scenario. Ordering is fully
        deterministic so the acceptance tests are not at the mercy of dict iteration.
        """
        state = self._state

        def rank(hypothesis) -> tuple[int, float, int]:
            supported = hypothesis.status.value == "SUPPORTED"
            return (
                0 if supported else 1,
                -hypothesis.confidence,
                hypothesis.times_suggested_to_user,
            )

        declaration_order = list(state.hypotheses.values())
        candidates = [
            h
            for h in declaration_order
            if not h.is_rejected and h.times_suggested_to_user <= self.MAX_SUGGESTIONS
        ]
        if not candidates:
            return None

        # Prefer a branch we have not already leaned on. A branch that only contains
        # hypotheses we have already put to the caller is not a change of strategy.
        untouched = [h for h in candidates if h.times_suggested_to_user == 0]
        pool = untouched or candidates
        pool.sort(key=lambda h: (rank(h), declaration_order.index(h)))
        return pool[0].branch

    # -- internals -----------------------------------------------------------

    def _guard_blocked_rejected_hypothesis(self) -> bool:
        """Did the output guard have to block a contradicted diagnosis?"""
        for event in self._state.recorder.of_type(EventType.OUTPUT_GUARD_REJECTION):
            violations = event.meta.get("violations") or []
            if "REJECTED_HYPOTHESIS" in violations:
                return True
            if event.meta.get("blocked_hypotheses"):
                return True
        return False

    def _spoke_rejected_hypothesis(self) -> bool:
        """Did a rejected hypothesis actually reach the caller after its rejection?

        This should always be False — the guard runs before speech. It is checked
        anyway so that a regression shows up as a loud loop signal instead of a
        quietly wrong conversation.
        """
        state = self._state
        for record in state.speech_records.values():
            if not record.was_heard:
                continue
            for hypothesis_id in record.asserted_hypotheses:
                hypothesis = state.get_hypothesis(hypothesis_id)
                if hypothesis is None or hypothesis.rejected_at_version is None:
                    continue
                if record.state_version >= hypothesis.rejected_at_version:
                    return True
        return False

    def _evidence_count(self) -> int:
        """How much we actually know: usable tool results plus confirmed facts.

        Stale results deliberately do not count. A superseded result arriving is not
        progress, and letting it reset the stagnation counter would let a slow tool
        mask a loop.
        """
        state = self._state
        usable = sum(1 for t in state.completed_tools if not t.stale and t.succeeded)
        return usable + len(state.confirmed_facts)

    def _spoken_diagnoses_pairs(self) -> list[tuple[str, int]]:
        return [(text, evidence) for text, _version, evidence in self._spoken_diagnoses]

    @staticmethod
    def _repeated_without_new_evidence(items: list[tuple[str, int]]) -> bool:
        seen: dict[str, int] = {}
        for key, evidence_count in items:
            if key in seen and evidence_count <= seen[key]:
                return True
            seen[key] = min(seen.get(key, evidence_count), evidence_count)
        return False
