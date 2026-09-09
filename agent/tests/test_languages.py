"""Language selection stays orthogonal to shared resolution invariants."""

from __future__ import annotations

from unloop.agent import ResolutionEngine, _split_sentence
from unloop.config import AppConfig
from unloop.language import configure_session_language, get_language
from unloop.prompts import build_instructions, correction_acknowledgement
from unloop.resolution.hypotheses import HypothesisStatus
from unloop.resolution.state import SpeechRecord


def test_hindi_profile_selects_supported_stt_and_rime_voice() -> None:
    profile = get_language("hindi")
    config = configure_session_language(AppConfig(), profile)

    assert config.stt.language == "hi"
    assert config.rime.model == "coda"
    assert config.rime.language == "hin"
    assert config.rime.speaker == "taru"
    assert config.rime.validate() == []


def test_hindi_danda_keeps_sentence_level_speech_streaming() -> None:
    sentence, remainder = _split_sentence("मैं जाँच करता हूँ। अगला कदम यह है।")

    assert sentence == "मैं जाँच करता हूँ।"
    assert remainder == " अगला कदम यह है।"


def test_hindi_prompt_and_safe_recovery_use_devanagari() -> None:
    profile = get_language("hindi")
    engine = ResolutionEngine(AppConfig(), domain_id="ecommerce", language_id="hindi")
    prompt = build_instructions(
        engine.state, system_prompt=engine.adapter.instructions(), language=profile
    )

    assert "देवनागरी" in prompt
    assert "आप सही कह रहे हैं" in correction_acknowledgement(
        "refund received", "payment trace", language=profile
    )


def _record_spoken_hypothesis(engine: ResolutionEngine, hypothesis_id: str, text: str) -> None:
    hypothesis = engine.state.get_hypothesis(hypothesis_id)
    assert hypothesis is not None
    hypothesis.times_suggested_to_user = 1
    engine.state.register_speech(
        SpeechRecord(
            speech_id=f"spoken_{hypothesis_id}",
            state_version=engine.state.state_version,
            text=text,
            asserted_hypotheses=[hypothesis_id],
            heard_status="COMPLETED",
            heard_text=text,
            started_at=1.0,
        )
    )


async def test_hindi_generic_denial_uses_same_correction_engine() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="hotel", language_id="hindi")
    await engine.on_user_transcript("होटल को मेरी बुकिंग नहीं मिल रही।")
    hypothesis = engine.state.get_hypothesis("HOTEL_HAS_BOOKING")
    assert hypothesis is not None
    _record_spoken_hypothesis(engine, "HOTEL_HAS_BOOKING", "होटल के पास आपकी बुकिंग है।")

    utterance = "नहीं, होटल को मेरी बुकिंग नहीं मिल रही।"
    engine.reconciler.apply(utterance, engine.extractor.extract(utterance, engine.state))

    assert hypothesis.status is HypothesisStatus.REJECTED
    assert engine.state.user_corrections[-1].raw_utterance.startswith("नहीं")


async def test_hindi_reassertion_of_rejected_hypothesis_is_blocked() -> None:
    engine = ResolutionEngine(AppConfig(), domain_id="hotel", language_id="hindi")
    await engine.on_user_transcript("होटल को मेरी बुकिंग नहीं मिल रही।")
    hypothesis = engine.state.get_hypothesis("HOTEL_HAS_BOOKING")
    assert hypothesis is not None
    _record_spoken_hypothesis(engine, "HOTEL_HAS_BOOKING", "होटल के पास आपकी बुकिंग है।")
    utterance = "नहीं, होटल को मेरी बुकिंग नहीं मिल रही।"
    engine.reconciler.apply(utterance, engine.extractor.extract(utterance, engine.state))

    verdict = engine.guard.check("होटल के पास आपकी बुकिंग मिल गई है।")

    assert verdict.allowed is False
    assert verdict.asserted_hypotheses == ("HOTEL_HAS_BOOKING",)
