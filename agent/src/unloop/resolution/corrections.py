"""Correction extraction and reconciliation.

When the caller says "no, my card is not blocked, I used it five minutes ago", three
separate things have happened:

1. a **hypothesis was contradicted** (``CARD_BLOCKED``),
2. **evidence was offered** ("used it five minutes ago"),
3. possibly a **redirect** ("check the OTP delivery instead").

A generic chatbot flattens all three into "user said something" and lets the model
decide what to do with it. UNLOOP extracts them as structured records and lets the
deterministic engine act on them, because acting on (1) is the entire product.

Extraction is pattern-based rather than model-based. That is a deliberate trade:
patterns miss paraphrases a model would catch, but they never *invent* a correction,
they are pinned by unit tests, and they cannot be talked out of firing. An LLM-proposed
extraction can be fed in through :meth:`CorrectionReconciler.apply_extraction` as well
— but it is treated as a proposal that the deterministic layer validates, never as an
authority. Recall limits are documented in docs/FAILURE_MODES.md rather than papered
over.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from ..observability.events import EventType
from ..tools.types import Subject
from .hypotheses import Evidence, EvidenceSource
from .state import Correction, ResolutionState


class ExtractionType(str, Enum):
    CORRECTION = "correction"
    """The caller contradicts a specific hypothesis."""

    REDIRECT = "redirect"
    """The caller asks us to investigate a different branch."""

    INEFFECTIVE = "ineffective"
    """The caller reports that what we tried did not help."""

    CONFIRMATION = "confirmation"
    """The caller confirms something we proposed."""


@dataclass(frozen=True)
class Extraction:
    """One structured thing found in a caller utterance."""

    type: ExtractionType
    target: str | None
    claim: str
    evidence: str
    invalidates: frozenset[Subject] = field(default_factory=frozenset)
    redirect_to: Subject | None = None
    raw: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.type.value,
            "target": self.target,
            "claim": self.claim,
            "evidence": self.evidence,
            "invalidates": sorted(s.value for s in self.invalidates),
            "redirect_to": self.redirect_to.value if self.redirect_to else None,
        }


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# --- denial patterns, per hypothesis ---------------------------------------
# Each entry: (hypothesis id, denial pattern, subjects the denial invalidates).
_DENIALS: tuple[tuple[str, re.Pattern[str], frozenset[Subject]], ...] = (
    (
        "CARD_BLOCKED",
        _rx(
            r"\bcard\b[^.?!]{0,30}\b(?:is\s+not|isn'?t|ain'?t|not|never\s+been|wasn'?t)\b"
            r"[^.?!]{0,15}\b(?:blocked|block|frozen|deactivated|disabled|suspended)\b"
            r"|\b(?:no|not)\b[^.?!]{0,15}\bcard\s+block\b"
            r"|\bcard\b[^.?!]{0,20}\b(?:is|works|working)\b[^.?!]{0,12}\b(?:fine|active|okay|ok|working)\b"
        ),
        frozenset({Subject.CARD}),
    ),
    (
        "ONLINE_TXN_DISABLED",
        _rx(
            r"\bonline\b[^.?!]{0,30}\b(?:is\s+not|isn'?t|are\s+not|aren'?t|not)\b"
            r"[^.?!]{0,15}\b(?:disabled|off|blocked)\b"
            r"|\bonline\s+(?:payments?|transactions?)\b[^.?!]{0,20}\b(?:work|working|fine|enabled|on)\b"
        ),
        frozenset({Subject.ONLINE_TXN}),
    ),
    (
        "MOBILE_NOT_REGISTERED",
        _rx(
            r"\b(?:number|mobile|phone)\b[^.?!]{0,30}\b(?:is\s+)?(?:correct|right|registered|verified|fine|same)\b"
            r"|\b(?:number|mobile|phone)\b[^.?!]{0,25}\b(?:has\s+not|hasn'?t|did\s+not|didn'?t)\s+chang"
        ),
        frozenset({Subject.MOBILE}),
    ),
)

# --- corroborating evidence the caller volunteers --------------------------
_EVIDENCE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        _rx(
            r"\b(?:used|use[d]?\s+it|paid|swiped|tapped|bought)\b[^.?!]{0,40}\b(?:ago|earlier|today|yesterday|this morning|just now|minutes?|hours?)\b"
        ),
        "caller reports recent successful card use",
    ),
    (
        _rx(
            r"\b(?:worked|working)\b[^.?!]{0,30}\b(?:earlier|before|yesterday|this morning|fine)\b"
        ),
        "caller reports the card worked recently",
    ),
    (
        _rx(r"\b(?:other|another)\s+(?:card|payment)s?\b[^.?!]{0,25}\bwork"),
        "caller reports another payment method works",
    ),
    (
        _rx(r"\bno\s+(?:sms|message|text|otp)\b[^.?!]{0,30}\b(?:at all|received|came|arrived)\b"),
        "caller reports no message received at all",
    ),
)

# --- explicit redirects -----------------------------------------------------
_REDIRECTS: tuple[tuple[re.Pattern[str], Subject], ...] = (
    (
        _rx(r"\bcheck\b[^.?!]{0,25}\b(?:o\.?t\.?p\.?|sms|message|text)\b[^.?!]{0,20}\bdeliver"),
        Subject.OTP_DELIVERY,
    ),
    (_rx(r"\b(?:o\.?t\.?p\.?|sms|message)\s+deliver\w*\b"), Subject.OTP_DELIVERY),
    (_rx(r"\bcheck\b[^.?!]{0,20}\b(?:my\s+)?(?:mobile|phone)\s+number\b"), Subject.MOBILE),
    (_rx(r"\bcheck\b[^.?!]{0,25}\bonline\s+(?:payments?|transactions?)\b"), Subject.ONLINE_TXN),
)

# --- "that didn't help" -----------------------------------------------------
_INEFFECTIVE = _rx(
    r"\b(?:that|it|this)\b[^.?!]{0,20}\b(?:did\s?n[o']?t|does\s?n[o']?t|has\s?n[o']?t)\b"
    r"[^.?!]{0,15}\b(?:work|help|fix|solve|resolve|change)\b"
    r"|\bstill\b[^.?!]{0,25}\b(?:not\s+(?:working|receiving|getting)|no\s+o\.?t\.?p\.?|same (?:issue|problem))\b"
    r"|\b(?:no|nothing)\s+(?:change|difference)\b"
    r"|\bsame\s+(?:thing|problem|issue)\b"
    r"|\b(?:abhi\s+bhi|phir\s+bhi)\b[^.?!]{0,30}\b(?:nahi|nahin)\b"
    r"|\b(?:kaam|help|solve|fix)\b[^.?!]{0,20}\b(?:nahi|nahin)\b"
    r"|\b(?:koi\s+)?(?:farq|fayda)\b[^.?!]{0,15}\b(?:nahi|nahin)\b"
    r"|(?:अभी भी|फिर भी)[^.?!]{0,30}(?:नहीं|नही)"
    r"|(?:काम|मदद|हल)[^.?!]{0,20}(?:नहीं|नही)"
)

# --- generic denial of whatever we just said -------------------------------
_GENERIC_DENIAL = _rx(
    r"^\s*(?:no|nope|nah)\b|"
    r"\bthat'?s\s+(?:not\s+(?:it|right|correct|true)|wrong|incorrect)\b|"
    r"\bnot\s+the\s+(?:issue|problem|case)\b|"
    r"^\s*(?:nahi|nahin|na)\b|"
    r"\b(?:yeh|ye|woh|vo)\b[^.?!]{0,20}\b(?:galat|nahi|nahin)\b|"
    r"\b(?:problem|issue|wajah|reason)\b[^.?!]{0,15}\b(?:nahi|nahin)\b|"
    r"^\s*(?:नहीं|नही|ना)(?:\s|,)|"
    r"(?:यह|ये|वह|वो)[^.?!]{0,20}(?:गलत|नहीं|नही)|"
    r"(?:समस्या|दिक्कत|कारण|वजह)[^.?!]{0,15}(?:नहीं|नही)"
)


class CorrectionExtractor:
    """Turns a caller utterance into structured extractions."""

    def __init__(
        self,
        *,
        denials: tuple[tuple[str, re.Pattern[str], frozenset[Subject]], ...] | None = None,
        evidence_patterns: tuple[tuple[re.Pattern[str], str], ...] | None = None,
        redirects: tuple[tuple[re.Pattern[str], Subject], ...] | None = None,
        hypothesis_subjects: dict[str, frozenset[Subject]] | None = None,
    ) -> None:
        self._denials = denials or _DENIALS
        self._evidence_patterns = evidence_patterns or _EVIDENCE_PATTERNS
        self._redirects = redirects or _REDIRECTS
        self._hypothesis_subjects = hypothesis_subjects

    def extract(self, utterance: str, state: ResolutionState) -> list[Extraction]:
        """Find every correction, redirect and complaint in one utterance.

        Order of the returned list is stable: explicit denials first, then redirects,
        then ineffectiveness reports. The caller of this method applies them in order,
        so a single sentence that both denies and redirects produces one version bump
        per distinct concern rather than an arbitrary interleaving.
        """
        text = utterance.strip()
        if not text:
            return []

        found: list[Extraction] = []
        evidence = self._extract_evidence(text)

        # 1. Explicit, targeted denials.
        denied: set[str] = set()
        for hypothesis_id, pattern, subjects in self._denials:
            if pattern.search(text):
                denied.add(hypothesis_id)
                hypothesis = state.get_hypothesis(hypothesis_id)
                label = hypothesis.label if hypothesis else hypothesis_id
                found.append(
                    Extraction(
                        type=ExtractionType.CORRECTION,
                        target=hypothesis_id,
                        claim=f"caller denies: {label}",
                        evidence=evidence or "caller asserts this is not the cause",
                        invalidates=subjects,
                        raw=text,
                    )
                )

        # 2. A bare "no, that's not it" denies whatever we most recently proposed.
        #    Only counted when nothing more specific matched, so "no, my card is not
        #    blocked" produces one correction rather than two.
        if not denied and _GENERIC_DENIAL.search(text):
            target = self._most_recently_suggested(state)
            if target is not None:
                hypothesis = state.get_hypothesis(target)
                label = hypothesis.label if hypothesis else target
                found.append(
                    Extraction(
                        type=ExtractionType.CORRECTION,
                        target=target,
                        claim=f"caller denies: {label}",
                        evidence=evidence or "caller rejected the stated diagnosis",
                        invalidates=self._subjects_for(target),
                        raw=text,
                    )
                )

        # 3. Redirects.
        for pattern, subject in self._redirects:
            if pattern.search(text):
                found.append(
                    Extraction(
                        type=ExtractionType.REDIRECT,
                        target=None,
                        claim=f"caller asks us to investigate {subject.value}",
                        evidence="explicit caller request",
                        redirect_to=subject,
                        raw=text,
                    )
                )
                break

        # 4. "That didn't work."
        if _INEFFECTIVE.search(text):
            found.append(
                Extraction(
                    type=ExtractionType.INEFFECTIVE,
                    target=None,
                    claim="caller reports the last step did not help",
                    evidence=evidence or "caller reports no change",
                    raw=text,
                )
            )

        return found

    def _extract_evidence(self, text: str) -> str:
        for pattern, summary in self._evidence_patterns:
            if pattern.search(text):
                return summary
        return ""

    def _subjects_for(self, hypothesis_id: str) -> frozenset[Subject]:
        if self._hypothesis_subjects is not None:
            return self._hypothesis_subjects.get(hypothesis_id, frozenset())
        return _subjects_for(hypothesis_id)

    def _most_recently_suggested(self, state: ResolutionState) -> str | None:
        """The last hypothesis we actually said out loud.

        Deliberately restricted to turns the caller *heard*: denying a diagnosis they
        were never told is not something a caller can do, and attributing one would
        corrupt the record.
        """
        for record in sorted(
            state.speech_records.values(),
            key=lambda r: r.started_at or 0.0,
            reverse=True,
        ):
            if not record.was_heard:
                continue
            for hypothesis_id in record.asserted_hypotheses:
                hypothesis = state.get_hypothesis(hypothesis_id)
                if hypothesis is not None and not hypothesis.is_rejected:
                    return hypothesis_id
        return None


def _subjects_for(hypothesis_id: str) -> frozenset[Subject]:
    from .output_guard import _HYPOTHESIS_SUBJECTS

    return _HYPOTHESIS_SUBJECTS.get(hypothesis_id, frozenset())


class CorrectionReconciler:
    """Applies extractions to state, reconciling caller claims with tool evidence.

    Reconciliation matters because the two can disagree. If the caller says the card
    is fine and the backend also says ``ACTIVE``, the rejection is doubly grounded. If
    the caller says the card is fine but the backend says ``BLOCKED``, we do **not**
    silently override the caller — we record both, reject the hypothesis on the
    caller's testimony (they are the one holding the card), and flag the conflict for
    the human who picks up the escalation. Quietly deciding the customer is wrong is
    the behaviour this product exists to eliminate.
    """

    def __init__(
        self,
        state: ResolutionState,
        *,
        conflict_resolver: Callable[[ResolutionState, str], str | None] | None = None,
    ) -> None:
        self._state = state
        self._conflict_resolver = conflict_resolver

    def apply(self, utterance: str, extractions: list[Extraction]) -> list[Correction]:
        applied: list[Correction] = []
        state = self._state

        for extraction in extractions:
            if extraction.type is ExtractionType.CORRECTION and extraction.target:
                applied.append(self._apply_correction(extraction, utterance))
            elif extraction.type is ExtractionType.REDIRECT and extraction.redirect_to:
                state.set_strategy(
                    f"investigate_{extraction.redirect_to.value}",
                    reason="caller redirect",
                )
            elif extraction.type is ExtractionType.INEFFECTIVE:
                state.recorder.emit(
                    EventType.LOOP_SIGNAL,
                    state_version=state.state_version,
                    signal="user_reports_ineffective",
                    utterance_preview=utterance[:120],
                )
        return applied

    def _apply_correction(self, extraction: Extraction, utterance: str) -> Correction:
        state = self._state
        target = extraction.target or ""

        correction = state.record_correction(
            target_hypothesis=target,
            claim=extraction.claim,
            evidence=extraction.evidence,
            invalidates=set(extraction.invalidates),
            raw_utterance=utterance,
        )

        # The correction is evidence in its own right, stamped with the version it
        # created. That stamping is what stops a pre-correction tool result from
        # being replayed later to undo the rejection (see Hypothesis.can_reactivate).
        evidence = Evidence(
            id=f"ev_{correction.id}",
            source=EvidenceSource.USER,
            summary=extraction.evidence,
            observed_at_version=state.state_version,
            supports=False,
            detail={"claim": extraction.claim, "utterance": utterance[:200]},
        )
        state.reject_hypothesis(target, evidence)

        conflict = self._tool_conflict(target)
        if conflict:
            state.recorder.emit(
                EventType.LOOP_SIGNAL,
                state_version=state.state_version,
                signal="caller_tool_conflict",
                hypothesis_id=target,
                detail=conflict,
            )
        return correction

    def _tool_conflict(self, hypothesis_id: str) -> str | None:
        """Does backend evidence contradict the caller's denial?

        Returns a description when it does. The hypothesis stays rejected either way;
        this only records the disagreement so it reaches the human.
        """
        state = self._state
        if self._conflict_resolver is not None:
            return self._conflict_resolver(state, hypothesis_id)
        if hypothesis_id != "CARD_BLOCKED":
            return None
        result = state.latest_result_for(Subject.CARD)
        if result is None:
            return None
        status = str(result.payload.get("card_status", "")).upper()
        if status and status != "ACTIVE":
            return f"backend reports card_status={status} while caller reports the card works"
        return None
