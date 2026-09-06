#!/usr/bin/env python3
"""Render the Results section of RIME_EVIDENCE.md from artifacts/results.json.

The competition asks that every number shown comes from a repeatable benchmark. The
cheapest way to guarantee that is to make the document physically incapable of
containing a hand-typed number: this script owns the region of RIME_EVIDENCE.md
between the two markers below, and rewrites it wholesale from the artifacts.

    python scripts/render_evidence_doc.py

Prose outside the markers is written by hand and left alone.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "RIME_EVIDENCE.md"
RESULTS = REPO_ROOT / "artifacts" / "results.json"

BEGIN = "<!-- BEGIN GENERATED: do not edit by hand; run scripts/render_evidence_doc.py -->"
END = "<!-- END GENERATED -->"


def render(results: dict) -> str:
    lines: list[str] = [BEGIN, ""]

    env = results.get("environment", {})
    rime = results.get("rime_config", {})
    totals = results.get("totals", {})
    harness = results.get("harness", {})

    lines += [
        (
            f"*Generated {results.get('timestamp')} from commit "
            f"`{str(results.get('git_commit'))[:12]}`"
            + ("  **(source tree was dirty)**" if results.get("source_tree_dirty") else "")
            + ".*"
        ),
        "",
        "### Environment",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Python | {env.get('python')} |",
        f"| Platform | {env.get('platform')} |",
        f"| livekit-agents | {env.get('livekit_agents')} |",
        f"| livekit-plugins-rime | {env.get('livekit_plugins_rime')} |",
        f"| Harness | {harness.get('kind')} |",
        f"| Injected `get_card_status` delay | {harness.get('injected_card_status_delay_ms')} ms |",
        "",
        "### Speech path as configured",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Provider | {rime.get('provider')} |",
        f"| Integration | {rime.get('integration')} |",
        f"| Model | `{rime.get('model')}` |",
        f"| Speaker | `{rime.get('speaker')}` |",
        f"| Language | `{rime.get('language')}` |",
        f"| Transport | {rime.get('transport')} |",
        f"| Configured base URL | `{rime.get('base_url')}` |",
        f"| Resolved endpoint | `{rime.get('resolved_endpoint')}` |",
        f"| Region | {rime.get('region')} |",
        f"| Audio format | {rime.get('audio_format')} |",
        f"| Sample rate | {rime.get('sample_rate')} Hz |",
        f"| Segmentation | `{rime.get('segment')}` |",
        f"| Plugin version | {rime.get('livekit_plugin_version')} |",
        f"| Config problems | {rime.get('config_problems') or 'none'} |",
        "",
        "### Acceptance results",
        "",
        (
            f"**{totals.get('passes')} of {totals.get('runs')} runs passed** "
            f"({results.get('duration_s')}s)."
        ),
        "",
        "| Scenario | Runs | Passed | Failed | Checks per run | Failed checks |",
        "|---|---:|---:|---:|---:|---|",
    ]

    for name, data in results.get("tests", {}).items():
        failed = ", ".join(data.get("failed_checks") or []) or "—"
        lines.append(
            f"| `{name}` | {data['runs']} | {data['passes']} | {data['failures']} | "
            f"{data['checks_per_run']} | {failed} |"
        )

    # Per-check detail for the primary scenario: the headline claim decomposed into
    # the individual properties that make it up.
    primary = results.get("tests", {}).get("primary_stale_fence")
    if primary:
        lines += [
            "",
            "#### `primary_stale_fence` — every check, every run",
            "",
            "| Check | Passed |",
            "|---|---:|",
        ]
        for check, passes in sorted(primary.get("per_check_passes", {}).items()):
            lines.append(f"| `{check}` | {passes}/{primary['runs']} |")

    # In-process timings, with their caveats attached rather than in a footnote.
    lines += ["", "### In-process timings", ""]
    notes = results.get("timing_notes", {})
    any_timing = False
    for name, data in results.get("tests", {}).items():
        timings = data.get("in_process_timings_ms") or {}
        if not timings:
            continue
        any_timing = True
        lines += [f"**`{name}`**", "", "| Measurement | p50 | p95 | min | max |", "|---|---:|---:|---:|---:|"]
        for key, stats in timings.items():
            lines.append(
                f"| `{key}` | {stats.get('p50')} | {stats.get('p95')} | "
                f"{stats.get('min')} | {stats.get('max')} | "
            )
        lines.append("")
        for key in timings:
            if key in notes:
                lines += [f"- **`{key}`** — {notes[key]}", ""]
    if not any_timing:
        lines.append("No in-process timings recorded.")
    if notes.get("caveat"):
        lines += [f"> {notes['caveat']}", ""]

    # The honest column: what has not been measured.
    lines += [
        "### Not yet measured",
        "",
        (
            "These require credentials or hardware that were not available when this "
            "artifact was generated. They are recorded as `null`, never estimated."
        ),
        "",
        "| Measurement | Status | Why |",
        "|---|---|---|",
    ]
    for name, data in results.get("not_yet_measured", {}).items():
        lines.append(f"| `{name}` | not measured | {data.get('reason')} |")

    lines += ["", END]
    return "\n".join(lines)


def main() -> int:
    if not RESULTS.is_file():
        print(f"missing {RESULTS}; run scripts/generate_evidence.py first", file=sys.stderr)
        return 1
    if not DOC.is_file():
        print(f"missing {DOC}", file=sys.stderr)
        return 1

    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    body = render(results)
    doc = DOC.read_text(encoding="utf-8")

    if BEGIN not in doc or END not in doc:
        print(f"{DOC.name} has no generated block; add the BEGIN/END markers", file=sys.stderr)
        return 1

    head = doc.split(BEGIN)[0]
    tail = doc.split(END, 1)[1]
    DOC.write_text(head + body + tail, encoding="utf-8")
    print(f"Rendered results into {DOC.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
