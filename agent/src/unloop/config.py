"""Configuration, and the machine-readable record of the speech path.

Two jobs:

1. turn environment variables into a typed, validated config;
2. emit ``artifacts/rime_config.json`` — the exact, verifiable description of the
   speech path a judge can check against the logs.

The ``/ws3`` handling in :meth:`RimeConfig.resolved_endpoint` is not incidental.
``livekit-plugins-rime`` 1.8.0 builds its own URL as ``f"{base_url}/ws3?{params}"``,
while Rime's own documentation quotes the endpoint *including* ``/ws3``. Copying the
documented value into ``base_url`` therefore produces ``.../ws3/ws3`` and fails at
connect time. We strip a trailing ``/ws3`` and say so loudly rather than letting
someone lose an evening to it.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger("unloop.config")

#: Models the installed plugin will accept. Read from livekit/plugins/rime/models.py
#: at audit time; "arcana" was retired 2026-08-19 and the plugin rejects it.
SUPPORTED_RIME_MODELS = ("coda", "mistv3", "mistv2")

#: Languages the plugin's TTSLangs literal accepts.
SUPPORTED_RIME_LANGS = ("eng", "spa", "fra", "ger", "hin")

#: WebSocket segmentation modes documented by Rime for /ws3.
SUPPORTED_SEGMENTS = ("bySentence", "immediate", "never")

#: Rime's regional WebSocket origins. The plugin's default is US West.
RIME_WS_REGIONS = {
    "us-west": "wss://users-ws.rime.ai",
    "us-east": "wss://users-east-ws.rime.ai",
}


class ConfigError(RuntimeError):
    """Raised for a configuration that would fail at runtime or misreport evidence."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class RimeConfig:
    """The judged speech path, in full."""

    api_key_present: bool
    model: str = "coda"
    speaker: str = "eyre"
    language: str = "eng"
    #: Origin only. Never includes /ws3 — see the module docstring.
    base_url: str = RIME_WS_REGIONS["us-west"]
    sample_rate: int = 24000
    segment: str = "bySentence"
    use_websocket: bool = True

    @classmethod
    def from_env(cls) -> RimeConfig:
        base_url = _env("RIME_BASE_URL") or RIME_WS_REGIONS["us-west"]
        return cls(
            api_key_present=bool(_env("RIME_API_KEY")),
            model=_env("RIME_MODEL") or "coda",
            speaker=_env("RIME_SPEAKER") or "eyre",
            language=_env("RIME_LANGUAGE") or "eng",
            base_url=cls.normalise_base_url(base_url),
            sample_rate=int(_env("RIME_SAMPLE_RATE") or 24000),
            segment=_env("RIME_SEGMENT") or "bySentence",
        )

    @staticmethod
    def normalise_base_url(url: str) -> str:
        """Strip a trailing ``/ws3`` (or ``/ws``/``/ws2``) and any trailing slash.

        The plugin appends the path itself. Passing Rime's documented full endpoint
        would silently produce ``/ws3/ws3``; this converts a subtle connection
        failure into a warning at startup.
        """
        cleaned = url.strip().rstrip("/")
        for suffix in ("/ws3", "/ws2", "/ws"):
            if cleaned.endswith(suffix):
                logger.warning(
                    "RIME_BASE_URL ended with %r; the LiveKit Rime plugin appends the "
                    "path itself, so %r has been trimmed to %r. Set the origin only.",
                    suffix,
                    url,
                    cleaned[: -len(suffix)],
                )
                cleaned = cleaned[: -len(suffix)]
        return cleaned

    @property
    def region(self) -> str:
        for name, origin in RIME_WS_REGIONS.items():
            if self.base_url == origin:
                return name
        return "custom"

    @property
    def transport(self) -> str:
        return "websocket" if self.use_websocket else "http"

    @property
    def audio_format(self) -> str:
        # The plugin hard-codes audioFormat=pcm on the WS query string and emits
        # mime_type "audio/pcm"; on the HTTP path it requests accept: audio/pcm.
        return "pcm_s16le"

    def resolved_endpoint(self) -> str:
        """The URL the plugin will actually open, reconstructed from its own logic.

        Mirrors ``livekit/plugins/rime/tts.py::_ws_url``. Recorded in the evidence
        artifact so "configured base URL" and "endpoint actually used" are two
        separate, checkable facts rather than one hopeful one.
        """
        params: dict[str, Any] = {
            "speaker": self.speaker,
            "modelId": self.model,
            "audioFormat": "pcm",
            "samplingRate": self.sample_rate,
            "segment": self.segment,
            "lang": self.language,
        }
        return f"{self.base_url}/ws3?{urlencode(params)}"

    def validate(self) -> list[str]:
        """Problems that would make the judged path wrong. Empty list means good."""
        problems: list[str] = []
        if self.model not in SUPPORTED_RIME_MODELS:
            problems.append(
                f"RIME_MODEL={self.model!r} is not accepted by the installed plugin "
                f"(supported: {', '.join(SUPPORTED_RIME_MODELS)})"
            )
        if self.language not in SUPPORTED_RIME_LANGS:
            problems.append(
                f"RIME_LANGUAGE={self.language!r} not in {', '.join(SUPPORTED_RIME_LANGS)}"
            )
        if self.segment not in SUPPORTED_SEGMENTS:
            problems.append(f"RIME_SEGMENT={self.segment!r} not in {', '.join(SUPPORTED_SEGMENTS)}")
        if self.sample_rate <= 0:
            problems.append(f"RIME_SAMPLE_RATE={self.sample_rate} must be positive")
        if "/ws3" in self.base_url:
            problems.append(
                f"RIME_BASE_URL={self.base_url!r} still contains /ws3; the plugin appends it"
            )
        if not self.base_url.startswith(("ws://", "wss://")) and self.use_websocket:
            problems.append(
                f"RIME_BASE_URL={self.base_url!r} is not a websocket URL but use_websocket is set"
            )
        return problems

    def plugin_kwargs(self) -> dict[str, Any]:
        """Exactly the kwargs handed to ``rime.TTS(...)``.

        Kept in one place so the evidence artifact and the running agent cannot drift
        apart: both read this method.
        """
        return {
            "model": self.model,
            "speaker": self.speaker,
            "lang": self.language,
            "base_url": self.base_url,
            "sample_rate": self.sample_rate,
            "segment": self.segment,
            "use_websocket": self.use_websocket,
        }


@dataclass(frozen=True)
class STTConfig:
    model: str = "deepgram/nova-3"
    language: str = "en"
    #: Support terms boosted across the demo domains. Banking terms remain first so
    #: the judged OTP path retains the same recognition bias.
    keyterms: tuple[str, ...] = (
        "OTP",
        "one time password",
        "debit card",
        "transaction",
        "authorization",
        "merchant",
        "registered mobile number",
        "SMS",
        "issuer",
        "payment gateway",
        "refund",
        "reservation",
        "restaurant",
        "appointment",
        "salon",
        "hotel booking",
        "confirmation",
        "rebook",
        "reschedule",
    )

    @classmethod
    def from_env(cls) -> STTConfig:
        return cls(
            model=_env("STT_MODEL") or "deepgram/nova-3",
            language=_env("STT_LANGUAGE") or "en",
        )


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "inference"
    model: str = "openai/gpt-4.1-mini"

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            provider=_env("LLM_PROVIDER") or "inference",
            model=_env("LLM_MODEL") or "openai/gpt-4.1-mini",
        )


@dataclass(frozen=True)
class AppConfig:
    env: str = "development"
    demo_mode: bool = True
    log_level: str = "INFO"
    artifacts_dir: Path = field(default_factory=lambda: Path("../artifacts"))
    default_fixture: str = "otp_slow_tool"
    rime: RimeConfig = field(default_factory=lambda: RimeConfig(api_key_present=False))
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def from_env(cls) -> AppConfig:
        return cls(
            env=_env("APP_ENV") or "development",
            demo_mode=_env_bool("DEMO_MODE", default=True),
            log_level=_env("LOG_LEVEL") or "INFO",
            artifacts_dir=Path(_env("UNLOOP_ARTIFACTS_DIR") or "../artifacts"),
            default_fixture=_env("UNLOOP_FIXTURE") or "otp_slow_tool",
            rime=RimeConfig.from_env(),
            stt=STTConfig.from_env(),
            llm=LLMConfig.from_env(),
        )

    @property
    def livekit_configured(self) -> bool:
        return all(_env(k) for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))

    def missing_credentials(self) -> list[str]:
        missing = [
            k for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET") if not _env(k)
        ]
        if not self.rime.api_key_present:
            missing.append("RIME_API_KEY")
        return missing


# ---------------------------------------------------------------------------
# Evidence artifact
# ---------------------------------------------------------------------------


def _plugin_version() -> str:
    try:
        from livekit.plugins.rime import __version__

        return str(__version__)
    except Exception:
        return "unknown"


def _agents_version() -> str:
    try:
        from livekit.agents import __version__

        return str(__version__)
    except Exception:
        return "unknown"


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def write_rime_config_artifact(
    config: AppConfig,
    *,
    path: Path | None = None,
    verified_against_catalog: bool | None = None,
) -> Path:
    """Write ``artifacts/rime_config.json``.

    Records the configured base URL and the resolved endpoint as separate fields —
    the ``/ws3`` hazard makes those two genuinely different facts. Contains no
    credentials: only whether a key was present, never any part of its value.
    """
    target = Path(path) if path else config.artifacts_dir / "rime_config.json"
    target.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "provider": "Rime",
        "integration": "livekit-plugins-rime (direct plugin, own RIME_API_KEY)",
        "model": config.rime.model,
        "speaker": config.rime.speaker,
        "language": config.rime.language,
        "base_url": config.rime.base_url,
        "resolved_endpoint": config.rime.resolved_endpoint(),
        "region": config.rime.region,
        "audio_format": config.rime.audio_format,
        "sample_rate": config.rime.sample_rate,
        "transport": config.rime.transport,
        "segment": config.rime.segment,
        "livekit_plugin_version": _plugin_version(),
        "livekit_agents_version": _agents_version(),
        "api_key_present": config.rime.api_key_present,
        "verified_against_live_catalog": verified_against_catalog,
        "config_problems": config.rime.validate(),
        "git_commit": _git_commit(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return target


def load_dotenv_if_present() -> None:
    """Load ``.env.local`` then ``.env`` if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for candidate in (".env.local", ".env"):
        path = Path(candidate)
        if path.is_file():
            load_dotenv(path, override=False)
