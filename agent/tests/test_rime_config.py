"""The Rime speech path: configuration, the /ws3 hazard, and evidence integrity.

These tests exist because the difference between "we claim Rime over WebSocket at
24 kHz" and "Rime over WebSocket at 24 kHz" is checkable, and should be checked. The
central one asks the *installed plugin* to build its own URL and compares it to the
URL we publish as evidence — so the artifact cannot drift away from reality.
"""

from __future__ import annotations

import json

import pytest

from unloop.config import (
    RIME_WS_REGIONS,
    AppConfig,
    RimeConfig,
    write_rime_config_artifact,
)


def make_config(**overrides) -> RimeConfig:
    base = {
        "api_key_present": True,
        "model": "coda",
        "speaker": "eyre",
        "language": "eng",
        "base_url": RIME_WS_REGIONS["us-west"],
        "sample_rate": 24000,
        "segment": "bySentence",
    }
    base.update(overrides)
    return RimeConfig(**base)


# ---------------------------------------------------------------------------
# The /ws3 double-path hazard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given",
    [
        "wss://users-ws.rime.ai/ws3",
        "wss://users-ws.rime.ai/ws3/",
        "wss://users-ws.rime.ai/",
        "wss://users-ws.rime.ai",
    ],
)
def test_documented_endpoint_forms_all_normalise_to_the_origin(given: str):
    """Rime documents the endpoint WITH /ws3; the plugin appends /ws3 itself.

    Copying Rime's documented URL into base_url would produce /ws3/ws3 and fail at
    connect time. Every plausible form a person would paste must land on the origin.
    """
    assert RimeConfig.normalise_base_url(given) == "wss://users-ws.rime.ai"


def test_a_base_url_still_containing_ws3_is_reported_as_a_problem():
    config = make_config(base_url="wss://users-ws.rime.ai/ws3")
    # Constructed directly, bypassing normalisation, to prove validate() is a real
    # second line of defence rather than a formality.
    assert any("/ws3" in problem for problem in config.validate())


def test_resolved_endpoint_matches_what_the_installed_plugin_actually_builds():
    """The evidence artifact must describe the real connection, not an idealised one.

    Constructs the real plugin object and asks it for its own WebSocket URL. If
    livekit-plugins-rime ever changes how it builds that URL, this fails and the
    evidence gets corrected rather than quietly becoming wrong.
    """
    from livekit.plugins import rime

    config = make_config()
    tts = rime.TTS(api_key="test-key-not-a-real-credential", **config.plugin_kwargs())
    try:
        assert tts._ws_url() == config.resolved_endpoint()
        assert "/ws3/ws3" not in tts._ws_url()
        assert tts._ws_url().startswith("wss://users-ws.rime.ai/ws3?")
    finally:
        pass


def test_plugin_accepts_our_configuration_and_reports_rime_as_the_provider():
    from livekit.plugins import rime

    config = make_config()
    tts = rime.TTS(api_key="test-key-not-a-real-credential", **config.plugin_kwargs())

    assert tts.provider == "Rime"
    assert tts.model == "coda"
    assert tts.sample_rate == 24000
    # WebSocket mode is what gives us streaming *and* the word timestamps that
    # ADR-006 depends on for measuring what the caller actually heard.
    assert tts.capabilities.streaming is True
    assert tts.capabilities.aligned_transcript is True


# ---------------------------------------------------------------------------
# Region selection
# ---------------------------------------------------------------------------


def test_both_documented_regions_are_recognised():
    assert make_config(base_url=RIME_WS_REGIONS["us-west"]).region == "us-west"
    assert make_config(base_url=RIME_WS_REGIONS["us-east"]).region == "us-east"
    assert make_config(base_url="wss://example.invalid").region == "custom"


def test_telephony_sample_rate_is_expressible():
    """Rime advises requesting 8 kHz directly for telephony rather than resampling."""
    config = make_config(sample_rate=8000)
    assert config.validate() == []
    assert "samplingRate=8000" in config.resolved_endpoint()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_retired_model_is_rejected():
    """Arcana was retired 2026-08-19 and the installed plugin refuses it."""
    problems = make_config(model="arcana").validate()
    assert any("arcana" in p for p in problems)


@pytest.mark.parametrize("model", ["coda", "mistv3", "mistv2"])
def test_currently_supported_models_validate(model: str):
    assert make_config(model=model).validate() == []


def test_unknown_segment_is_rejected():
    assert any("segment" in p.lower() for p in make_config(segment="perWord").validate())


# ---------------------------------------------------------------------------
# Evidence artifact
# ---------------------------------------------------------------------------


def test_artifact_records_the_full_path_and_no_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("RIME_API_KEY", "sk-not-a-real-key-abcdef123456")
    monkeypatch.setenv("RIME_SPEAKER", "eyre")
    monkeypatch.setenv("RIME_BASE_URL", "wss://users-east-ws.rime.ai/ws3")  # with the hazard

    config = AppConfig.from_env()
    target = tmp_path / "rime_config.json"
    write_rime_config_artifact(config, path=target)

    record = json.loads(target.read_text(encoding="utf-8"))

    required = {
        "provider",
        "model",
        "speaker",
        "language",
        "base_url",
        "resolved_endpoint",
        "audio_format",
        "sample_rate",
        "transport",
        "segment",
        "livekit_plugin_version",
        "timestamp",
    }
    assert required <= set(record)

    assert record["provider"] == "Rime"
    assert record["transport"] == "websocket"
    # base_url and resolved_endpoint are deliberately separate facts.
    assert record["base_url"] == "wss://users-east-ws.rime.ai"
    assert record["resolved_endpoint"].startswith("wss://users-east-ws.rime.ai/ws3?")
    assert record["region"] == "us-east"
    assert record["config_problems"] == []

    # The key is never written, in any form.
    raw = target.read_text(encoding="utf-8")
    assert "sk-not-a-real-key" not in raw
    assert record["api_key_present"] is True
