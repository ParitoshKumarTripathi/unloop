#!/usr/bin/env python3
"""Verify the configured Rime model/speaker/language against the LIVE catalog.

The competition asks for a current production configuration. Rather than asserting
one in prose, this checks it: Rime publishes its catalog as unauthenticated JSON, so
the claim can be re-verified by anyone, at judging time, from a clean clone.

    python scripts/verify_rime_catalog.py
    python scripts/verify_rime_catalog.py --model coda --speaker eyre --lang eng
    python scripts/verify_rime_catalog.py --list-support-voices

Exit codes: 0 verified, 1 not in catalog, 2 catalog unreachable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CATALOG_URL = "https://users.rime.ai/data/voices/all-v2.json"
DETAILS_URL = "https://users.rime.ai/data/voices/voice_details.json"

#: Accepted by livekit-plugins-rime 1.8.0 (livekit/plugins/rime/models.py).
#: "arcana" still appears in the catalog JSON but the plugin rejects it at runtime,
#: so a catalog hit alone is not sufficient — both checks must pass.
PLUGIN_MODELS = ("coda", "mistv3", "mistv2")

REPO_ROOT = Path(__file__).resolve().parent.parent


def fetch(url: str, timeout: float = 20.0) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "unloop-catalog-check/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
        return json.loads(response.read().decode("utf-8"))


def load_env_defaults() -> dict[str, str]:
    """Read RIME_* from the environment, falling back to agent/.env.local."""
    values = {
        "model": os.environ.get("RIME_MODEL", ""),
        "speaker": os.environ.get("RIME_SPEAKER", ""),
        "lang": os.environ.get("RIME_LANGUAGE", ""),
    }
    env_file = REPO_ROOT / "agent" / ".env.local"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw = line.partition("=")
            key, raw = key.strip(), raw.strip()
            mapping = {"RIME_MODEL": "model", "RIME_SPEAKER": "speaker", "RIME_LANGUAGE": "lang"}
            field = mapping.get(key)
            if field and not values[field]:
                values[field] = raw
    return {
        "model": values["model"] or "coda",
        "speaker": values["speaker"] or "eyre",
        "lang": values["lang"] or "eng",
    }


def main() -> int:
    defaults = load_env_defaults()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=defaults["model"])
    parser.add_argument("--speaker", default=defaults["speaker"])
    parser.add_argument("--lang", default=defaults["lang"])
    parser.add_argument(
        "--list-support-voices",
        action="store_true",
        help="Print flagship voices whose catalog styles suit a support line.",
    )
    parser.add_argument(
        "--write-artifact",
        action="store_true",
        help="Write artifacts/rime_catalog_check.json with the verification result.",
    )
    args = parser.parse_args()

    try:
        catalog = fetch(CATALOG_URL)
        details = fetch(DETAILS_URL)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"FAIL: could not reach the Rime catalog: {exc}", file=sys.stderr)
        return 2

    print(f"Rime catalog fetched: {len(details)} voice records, models: {', '.join(sorted(catalog))}")

    if args.list_support_voices:
        wanted = {"professional", "formal", "more professional", "more formal"}
        rows = [
            v
            for v in details
            if v.get("modelId") == args.model
            and v.get("lang") == args.lang
            and v.get("flagship")
            and wanted & set(v.get("styles") or [])
        ]
        print(f"\nSupport-appropriate flagship voices for {args.model}/{args.lang}:")
        for voice in sorted(rows, key=lambda v: v["speaker"]):
            print(
                f"  {voice['speaker']:<12} {voice.get('gender',''):<7} "
                f"{voice.get('age',''):<12} {voice.get('description','')}"
            )
        print()

    problems: list[str] = []

    if args.model not in PLUGIN_MODELS:
        problems.append(
            f"model {args.model!r} is not accepted by livekit-plugins-rime 1.8.0 "
            f"(accepted: {', '.join(PLUGIN_MODELS)})"
        )
    if args.model not in catalog:
        problems.append(f"model {args.model!r} is not in the live catalog")
    else:
        langs = catalog[args.model]
        if args.lang not in langs:
            problems.append(
                f"language {args.lang!r} not offered for {args.model!r} "
                f"(available: {', '.join(sorted(langs))})"
            )
        elif args.speaker not in langs[args.lang]:
            problems.append(
                f"speaker {args.speaker!r} is not in the live catalog for "
                f"{args.model}/{args.lang} ({len(langs[args.lang])} voices available)"
            )

    voice_record = next(
        (
            v
            for v in details
            if v.get("speaker") == args.speaker
            and v.get("modelId") == args.model
            and v.get("lang") == args.lang
        ),
        None,
    )

    verified = not problems
    if verified:
        print(f"OK: {args.model}/{args.lang}/{args.speaker} exists in the live Rime catalog")
        if voice_record:
            print(
                f"    {voice_record.get('gender','?')}, {voice_record.get('age','?')}, "
                f"{voice_record.get('country','?')} | styles: "
                f"{', '.join(voice_record.get('styles') or []) or 'n/a'}"
            )
            if voice_record.get("description"):
                print(f'    "{voice_record["description"]}"')
    else:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)

    if args.write_artifact:
        artifact = REPO_ROOT / "artifacts" / "rime_catalog_check.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            json.dumps(
                {
                    "catalog_url": CATALOG_URL,
                    "checked": {"model": args.model, "speaker": args.speaker, "lang": args.lang},
                    "verified": verified,
                    "problems": problems,
                    "voice_record": voice_record,
                    "models_in_catalog": sorted(catalog),
                    "plugin_accepted_models": list(PLUGIN_MODELS),
                    "voice_count_for_model_lang": len(catalog.get(args.model, {}).get(args.lang, [])),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {artifact.relative_to(REPO_ROOT)}")

    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
