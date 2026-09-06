#!/usr/bin/env python3
"""Benchmark the real Rime speech path.

Answers the questions the Phase 0 audit deliberately left open rather than guessing:

* **Region** - is ``users-ws`` (US West) or ``users-east-ws`` (US East) faster *from
  this machine*? Run it from the deployed worker for the number that matters.
* **Segmentation** - does ``segment="immediate"`` actually beat ``"bySentence"`` on
  time-to-first-audio, given LiveKit already feeds the plugin sentence-tokenised text?
* **Model** - how much time-to-first-audio does ``coda`` cost against ``mistv3``?
* **Voice** - writes a WAV per shortlisted speaker so the choice comes from listening
  rather than from a catalog description.
* **Sample rate** - 8 kHz (telephony) against 24 kHz (Coda native).

Everything is measured through the installed ``livekit-plugins-rime``, over the same
WebSocket path the agent uses, so the numbers describe the shipped configuration.

Requires RIME_API_KEY. Without it the script explains what it would have measured and
exits 2, rather than emitting placeholder numbers.

    python scripts/run_voice_benchmark.py --regions
    python scripts/run_voice_benchmark.py --segments --runs 10
    python scripts/run_voice_benchmark.py --voices
    python scripts/run_voice_benchmark.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import sys
import time
import wave
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

#: Shortlist from the Phase 0 catalog audit: Coda English flagship voices whose
#: catalog styles include "professional" or "formal". A support line wants calm and
#: legible, so these are the candidates a listening test should decide between.
VOICE_SHORTLIST = ("eyre", "lintel", "bancroft", "cupola", "clementine")

REGIONS = {
    "us-west": "wss://users-ws.rime.ai",
    "us-east": "wss://users-east-ws.rime.ai",
}

#: Written for the ear, and deliberately full of the things that break TTS in this
#: domain: an initialism, a four-digit sequence, a time, and a rupee amount.
PRONUNCIATION_PROBE = (
    "Your card ending 4 8 2 1 is active. "
    "The O T P was generated at 4:15 p.m. for a payment of 2,499 rupees, "
    "but the message was never delivered."
)

BENCH_SENTENCE = (
    "Your card is showing as active, so a card block doesn't explain this. "
    "The one-time password was generated, but delivery failed."
)


def require_key() -> str:
    key = os.environ.get("RIME_API_KEY", "").strip()
    if not key:
        print(
            "RIME_API_KEY is not set.\n\n"
            "This script measures the real Rime path and will not invent numbers "
            "without it. With a key it would measure:\n"
            "  - time to first audio, us-west vs us-east, from this machine\n"
            "  - bySentence vs immediate segmentation\n"
            "  - coda vs mistv3\n"
            "  - 8 kHz (telephony) vs 24 kHz (Coda native)\n"
            "  - a WAV per shortlisted voice for a listening test\n\n"
            "Set RIME_API_KEY in agent/.env.local and re-run.",
            file=sys.stderr,
        )
        return ""
    return key


def build_tts(*, model: str, speaker: str, base_url: str, segment: str, sample_rate: int) -> Any:
    """Construct a TTS with the same kwargs the agent uses."""
    from livekit.plugins import rime

    return rime.TTS(
        model=model,
        speaker=speaker,
        lang="eng",
        base_url=base_url,
        sample_rate=sample_rate,
        segment=segment,
        use_websocket=True,
    )


async def synth_once(tts: Any, text: str, *, save_to: Path | None = None) -> dict[str, Any]:
    """Synthesise one utterance on an EXISTING TTS, returning time-to-first-audio.

    Takes the TTS as an argument rather than constructing one, which matters more than
    it looks: the plugin keeps a WebSocket connection pool on the TTS instance.
    Building a new TTS per measurement would pay TCP, TLS and WebSocket handshake
    every time, so every sample would be a cold sample and calling any of them "warm"
    would be a mislabelled measurement.

    ``ttfa_ms`` runs from pushing text to the first audio frame emitted by the plugin.
    It is client-side and therefore includes network round-trip - which is the point,
    since that is what the region comparison is about.
    """
    frames: list[Any] = []
    started = time.perf_counter()
    first_audio_at: float | None = None

    stream = tts.stream()
    stream.push_text(text)
    stream.flush()
    stream.end_input()

    async for event in stream:
        if first_audio_at is None:
            first_audio_at = time.perf_counter()
        frames.append(event.frame)
    await stream.aclose()

    finished = time.perf_counter()

    if save_to is not None and frames:
        save_to.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(save_to), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(tts.sample_rate)
            for frame in frames:
                handle.writeframes(frame.data.tobytes())

    audio_ms = (
        sum(f.samples_per_channel for f in frames) / tts.sample_rate * 1000 if frames else 0.0
    )
    return {
        "ttfa_ms": round((first_audio_at - started) * 1000, 2) if first_audio_at else None,
        "total_ms": round((finished - started) * 1000, 2),
        "audio_ms": round(audio_ms, 1),
        "frames": len(frames),
    }


def summarise(samples: list[float]) -> dict[str, float | None]:
    if not samples:
        return {"p50": None, "p95": None, "min": None, "max": None, "n": 0}
    ordered = sorted(samples)
    return {
        "p50": round(statistics.median(ordered), 2),
        "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2),
        "min": round(ordered[0], 2),
        "max": round(ordered[-1], 2),
        "n": len(ordered),
    }


async def bench_dimension(
    label: str,
    variants: dict[str, dict[str, Any]],
    *,
    runs: int,
) -> dict[str, Any]:
    """Measure each variant: one cold call, then ``runs`` warm calls on a pooled socket.

    Cold and warm are reported separately because they measure different things. Cold
    includes TCP, TLS and WebSocket handshake to the region; warm reuses the plugin's
    pooled connection and is what a running agent experiences between turns. Averaging
    them would hide both.
    """
    print("\n=== " + label + " ===")
    out: dict[str, Any] = {}
    for name, kwargs in variants.items():
        tts = build_tts(**kwargs)
        try:
            cold = await synth_once(tts, BENCH_SENTENCE)
            warm_samples: list[float] = []
            for _ in range(runs):
                sample = await synth_once(tts, BENCH_SENTENCE)
                if sample["ttfa_ms"] is not None:
                    warm_samples.append(sample["ttfa_ms"])
            warm = summarise(warm_samples)
            out[name] = {
                "config": dict(kwargs),
                "cold_ttfa_ms": cold["ttfa_ms"],
                "warm_ttfa_ms": warm,
                "audio_ms": cold["audio_ms"],
                "resolved_endpoint": tts._ws_url(),
            }
            print(f"  {name:<24} cold {cold['ttfa_ms']:>9} ms    warm p50 {warm['p50']:>9} ms")
        except Exception as exc:  # noqa: BLE001 - a failing variant must not lose the rest
            out[name] = {"config": dict(kwargs), "error": f"{type(exc).__name__}: {exc}"}
            print(f"  {name:<24} FAILED: {type(exc).__name__}: {exc}")
        finally:
            await tts.aclose()
    return out


async def bench_voices(out_dir: Path, sample_rate: int, base_url: str) -> dict[str, Any]:
    """Render the shortlist so the voice choice comes from listening, not a blurb."""
    print("\n=== voices (listening test) ===")
    results: dict[str, Any] = {}
    for speaker in VOICE_SHORTLIST:
        target = out_dir / f"voice_{speaker}.wav"
        tts = build_tts(
            model="coda",
            speaker=speaker,
            base_url=base_url,
            segment="bySentence",
            sample_rate=sample_rate,
        )
        try:
            sample = await synth_once(tts, PRONUNCIATION_PROBE, save_to=target)
            # Speaking rate is the one objective thing that separates these voices,
            # and it is not in the catalog. Identical text, so duration is directly
            # comparable. A support line wants unhurried but not tedious; anything
            # far outside roughly 120-170 wpm is worth listening to sceptically.
            words = len(PRONUNCIATION_PROBE.split())
            wpm = round(words / (sample["audio_ms"] / 60_000), 1) if sample["audio_ms"] else None
            results[speaker] = {
                "ttfa_ms": sample["ttfa_ms"],
                "audio_ms": sample["audio_ms"],
                "words_per_minute": wpm,
                "probe_words": words,
                "wav": str(target.relative_to(REPO_ROOT)).replace("\\", "/"),
            }
            print(
                f"  {speaker:<12} -> {target.name:<24} "
                f"{sample['audio_ms'] / 1000:>5.1f}s   {wpm} wpm"
            )
        except Exception as exc:  # noqa: BLE001
            results[speaker] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"  {speaker:<12} FAILED: {exc}")
        finally:
            await tts.aclose()
    print("\n  Listen to each before choosing. A catalog description is not a substitute.")
    return results


async def main_async(args: argparse.Namespace) -> int:
    document: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": (
            "Client-side measurements through livekit-plugins-rime over the same "
            "WebSocket path the agent uses. TTFA includes network round-trip, so it is "
            "dominated by the distance between this machine and the Rime region. Cold "
            "(new connection: TCP + TLS + WebSocket handshake) and warm (pooled "
            "connection, what a running agent sees between turns) are reported "
            "separately and must not be averaged together."
        ),
        "measured_from": {
            "platform": platform.platform(),
            "caveat": (
                "Rime serves us-east-1 and us-west-2 only. A measurement taken far from "
                "both says more about geography than about Rime. Re-run from the "
                "deployed worker for the number that describes production."
            ),
        },
        "runs_per_variant": args.runs,
    }

    run_all = args.all or not any(
        (args.regions, args.segments, args.models, args.rates, args.voices)
    )

    if args.regions or run_all:
        document["regions"] = await bench_dimension(
            "regions",
            {
                name: {
                    "model": "coda",
                    "speaker": args.speaker,
                    "base_url": url,
                    "segment": "bySentence",
                    "sample_rate": 24000,
                }
                for name, url in REGIONS.items()
            },
            runs=args.runs,
        )

    if args.segments or run_all:
        document["segments"] = await bench_dimension(
            "segmentation",
            {
                seg: {
                    "model": "coda",
                    "speaker": args.speaker,
                    "base_url": REGIONS[args.region],
                    "segment": seg,
                    "sample_rate": 24000,
                }
                for seg in ("bySentence", "immediate")
            },
            runs=args.runs,
        )

    if args.models or run_all:
        document["models"] = await bench_dimension(
            "models",
            {
                f"coda/{args.speaker}": {
                    "model": "coda",
                    "speaker": args.speaker,
                    "base_url": REGIONS[args.region],
                    "segment": "bySentence",
                    "sample_rate": 24000,
                },
                "mistv3/cove": {
                    "model": "mistv3",
                    "speaker": "cove",
                    "base_url": REGIONS[args.region],
                    "segment": "bySentence",
                    "sample_rate": 22050,
                },
            },
            runs=args.runs,
        )

    if args.rates or run_all:
        document["sample_rates"] = await bench_dimension(
            "sample rates (8 kHz is the telephony path)",
            {
                f"{rate}Hz": {
                    "model": "coda",
                    "speaker": args.speaker,
                    "base_url": REGIONS[args.region],
                    "segment": "bySentence",
                    "sample_rate": rate,
                }
                for rate in (8000, 16000, 24000)
            },
            runs=args.runs,
        )

    if args.voices or run_all:
        document["voices"] = await bench_voices(Path(args.out), 24000, REGIONS[args.region])

    target = REPO_ROOT / "artifacts" / "voice_benchmark.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if target.is_file():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    # Merge, so running one dimension at a time does not wipe the others.
    existing.update(document)
    target.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    print("\nWrote " + str(target.relative_to(REPO_ROOT)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--regions", action="store_true")
    parser.add_argument("--segments", action="store_true")
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--rates", action="store_true")
    parser.add_argument("--voices", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--runs", type=int, default=8, help="warm runs per variant")
    parser.add_argument("--speaker", default=os.environ.get("RIME_SPEAKER", "eyre"))
    parser.add_argument("--region", default="us-west", choices=sorted(REGIONS))
    parser.add_argument("--out", default=str(REPO_ROOT / "artifacts" / "audio"))
    args = parser.parse_args()

    # Load .env.local BEFORE checking for the key - otherwise the script reports a
    # missing credential that is sitting in the file it was about to read.
    try:
        from dotenv import load_dotenv

        env_file = REPO_ROOT / "agent" / ".env.local"
        if env_file.is_file():
            load_dotenv(env_file, override=False)
    except ImportError:
        pass

    if not require_key():
        return 2

    async def _run() -> int:
        from livekit.agents import utils

        # One http session context around every measurement, so the plugin's
        # connection pool survives across runs and "warm" genuinely means warm.
        async with utils.http_context.open():
            return await main_async(args)

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
