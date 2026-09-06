#!/usr/bin/env python3
"""Run the acceptance scenarios and write machine-generated evidence.

Produces:

* ``artifacts/results.json``  — per-scenario pass/fail counts and timing percentiles
* ``artifacts/events/*.jsonl`` — the raw event timeline for every run
* ``artifacts/rime_config.json`` — the exact speech path (written by config.py)

Two rules this script follows, because the competition is judged on evidence:

1. **Nothing is typed by hand.** Every number in ``results.json`` comes from a run
   that happened when the file was written. The tables in ``RIME_EVIDENCE.md`` are
   generated from this file, not transcribed into it.

2. **Unmeasured is written as ``null``, never as an estimate.** Anything that needs
   a live LiveKit session or a real Rime socket — interruption-to-audio-stop, Rime
   time-to-first-audio, telephony — appears with ``"measured": false`` and a reason.
   A plausible-looking number in an evidence file is worse than an empty one.

Usage:
    python scripts/generate_evidence.py                # 20 runs per scenario
    python scripts/generate_evidence.py --runs 5       # quicker
    python scripts/generate_evidence.py --delay-ms 3000  # full stress timing
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from unloop.config import AppConfig, write_rime_config_artifact
from unloop.harness import SCENARIOS, run_scenario


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def git_dirty() -> bool:
    """Was the SOURCE tree dirty when this run started?

    ``artifacts/`` is excluded deliberately. This script rewrites those files as its
    whole purpose, so including them would report "dirty" on every single run and the
    flag would carry no information. The question a reader actually needs answered is
    whether the *code* that produced these numbers was committed.
    """
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", ".", ":(exclude)artifacts"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return bool(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return False


def percentiles(values: list[float]) -> dict[str, float | None]:
    """p50 / p95 / max, or nulls when there is nothing to summarise."""
    if not values:
        return {"p50": None, "p95": None, "max": None, "min": None}
    ordered = sorted(values)
    return {
        "p50": round(statistics.median(ordered), 3),
        "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "max": round(max(ordered), 3),
        "min": round(min(ordered), 3),
    }


async def run_all(runs: int, delay_ms: int, events_dir: Path) -> dict[str, Any]:
    events_dir.mkdir(parents=True, exist_ok=True)
    for stale in events_dir.glob("*.jsonl"):
        stale.unlink()

    results: dict[str, Any] = {}

    for name in SCENARIOS:
        outcomes = []
        for index in range(runs):
            outcome = await run_scenario(
                name,
                run_index=index,
                delay_ms=delay_ms if name == "primary_stale_fence" else None,
            )
            outcomes.append(outcome)

            # Raw events are kept for every run, not just failures. A judge should be
            # able to open one and watch the fence work.
            path = events_dir / f"{name}_{index:03d}.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for event in outcome.events:
                    handle.write(json.dumps(event, default=str, separators=(",", ":")) + "\n")

        passes = sum(1 for o in outcomes if o.passed)

        # Per-check tallies, so a partial failure is visible rather than hidden
        # inside an overall pass rate.
        check_names = sorted({k for o in outcomes for k in o.checks})
        per_check = {
            check: sum(1 for o in outcomes if o.checks.get(check)) for check in check_names
        }

        timing_keys = sorted({k for o in outcomes for k in o.measured})
        timings = {
            key: percentiles([o.measured[key] for o in outcomes if key in o.measured])
            for key in timing_keys
        }

        results[name] = {
            "runs": runs,
            "passes": passes,
            "failures": runs - passes,
            "checks_per_run": len(check_names),
            "per_check_passes": per_check,
            "failed_checks": sorted({f for o in outcomes for f in o.failures}),
            "in_process_timings_ms": timings,
        }
        status = "PASS" if passes == runs else "FAIL"
        print(f"  {status}  {name}: {passes}/{runs} runs, {len(check_names)} checks each")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=20, help="runs per scenario (default 20)")
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=300,
        help="injected get_card_status delay for the stress scenario. 300 keeps the "
        "suite quick; 3000 matches the demo. The fence behaviour is identical either "
        "way - only the wall-clock wait differs.",
    )
    args = parser.parse_args()

    artifacts = REPO_ROOT / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    config = AppConfig.from_env()
    write_rime_config_artifact(config, path=artifacts / "rime_config.json")

    print(f"UNLOOP evidence run: {args.runs} runs per scenario, delay {args.delay_ms} ms")
    started = time.time()
    scenario_results = asyncio.run(run_all(args.runs, args.delay_ms, artifacts / "events"))
    elapsed = time.time() - started

    total_runs = sum(r["runs"] for r in scenario_results.values())
    total_passes = sum(r["passes"] for r in scenario_results.values())

    document = {
        "git_commit": git_commit(),
        "source_tree_dirty": git_dirty(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_s": round(elapsed, 2),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "livekit_agents": _version("livekit.agents"),
            "livekit_plugins_rime": _version("livekit.plugins.rime"),
        },
        "harness": {
            "kind": "in-process deterministic",
            "covers": [
                "tool dispatch with injected latency",
                "correction extraction and reconciliation",
                "hypothesis rejection and re-activation rules",
                "stale-result fence",
                "output guard",
                "loop detection",
                "handoff packet construction",
            ],
            "does_not_cover": [
                "audio capture or playback",
                "LiveKit realtime session behaviour",
                "Rime synthesis over the network",
                "SIP telephony",
            ],
            "injected_card_status_delay_ms": args.delay_ms,
        },
        "timing_notes": {
            "correction_apply_ms": (
                "Time to extract a correction from the caller's utterance, reject the "
                "contradicted hypothesis and increment the state version. Pure "
                "in-process CPU work, no I/O. This is the cost of the mechanism itself."
            ),
            "correction_to_fence_ms": (
                "Wall-clock time from the correction being applied to the in-flight "
                "tool result being classified by the fence. NOT a measure of fence "
                "speed: it is dominated by the remainder of the injected "
                f"{args.delay_ms} ms tool delay, because the fence cannot classify a "
                "result that has not arrived yet. Reported because it shows the "
                "correction genuinely lands while the tool is still in flight, which is "
                "the precondition the stress case depends on."
            ),
            "caveat": (
                "All timings here are in-process. None of them include audio capture, "
                "network, synthesis or playback. Do not read them as end-to-end voice "
                "latencies - those are listed under not_yet_measured."
            ),
        },
        "rime_config": json.loads((artifacts / "rime_config.json").read_text(encoding="utf-8")),
        "totals": {"runs": total_runs, "passes": total_passes, "failures": total_runs - total_passes},
        "tests": scenario_results,
        "not_yet_measured": {
            "interruption_to_obsolete_audio_stop_ms": {
                "runs": 0,
                "p50": None,
                "p95": None,
                "max": None,
                "measured": False,
                "reason": (
                    "Requires a live LiveKit session with real audio. No credentials "
                    "were configured when this run was generated. No target is claimed "
                    "until a baseline is measured."
                ),
            },
            "rime_time_to_first_audio_ms": {
                "runs": 0,
                "p50": None,
                "p95": None,
                "measured": False,
                "reason": "Requires RIME_API_KEY. Run scripts/run_voice_benchmark.py.",
            },
            "rime_region_comparison": {
                "measured": False,
                "reason": (
                    "us-west and us-east must be compared from the deployed worker's "
                    "region, not from a developer laptop. Run after deployment."
                ),
            },
            "telephony_sip_path": {
                "measured": False,
                "reason": "No SIP trunk configured yet (Phase 9).",
            },
        },
    }

    target = artifacts / "results.json"
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"Totals: {total_passes}/{total_runs} runs passed in {elapsed:.1f}s")
    print(f"Wrote {target.relative_to(REPO_ROOT)}")
    print(f"Wrote {len(list((artifacts / 'events').glob('*.jsonl')))} event logs to artifacts/events/")
    return 0 if total_passes == total_runs else 1


def _version(module: str) -> str:
    try:
        import importlib

        return str(getattr(importlib.import_module(module), "__version__", "unknown"))
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
