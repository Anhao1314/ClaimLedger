#!/usr/bin/env python3
"""Run resumable LongMemEval session extraction on the free OpenRouter channel.

Examples:
  # pilot five sessions on dev; no ingest yet
  python benchmarks/longmemeval/extract.py --split dev --max-sessions 5

  # continue the same prompt version, then build per-question claim stores
  python benchmarks/longmemeval/extract.py --split dev --ingest

  # rebuild stores from already-written session outputs, no API calls
  python benchmarks/longmemeval/extract.py --split dev --ingest-only

Keys are read from the environment only. The script never prints or writes them.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import common
import extraction


def split_ids(stats, split):
    if split not in ("dev", "report"):
        raise SystemExit("split must be dev or report")
    return stats["splits"][split]["ids"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "report"], required=True)
    parser.add_argument("--data", default=str(common.DATA))
    parser.add_argument("--stats", default=str(common.STATS))
    parser.add_argument("--out", help="run directory (default: runs/<split>/<prompt-version>)")
    parser.add_argument("--prompt-version", default=extraction.PROMPT_VERSION)
    parser.add_argument("--max-sessions", type=int, help="process at most N new sessions")
    parser.add_argument("--question", help="restrict to one question id")
    parser.add_argument("--no-resume", action="store_true",
                        help="re-extract even when a valid session output exists")
    parser.add_argument("--clear-stop", action="store_true",
                        help="remove a prior STOP marker after human review")
    parser.add_argument("--mock", action="store_true",
                        help="offline deterministic client for pipeline tests; not reportable")
    parser.add_argument("--ingest", action="store_true",
                        help="rebuild per-question ClaimStores after extraction")
    parser.add_argument("--ingest-only", action="store_true",
                        help="skip API calls; rebuild stores from existing outputs")
    parser.add_argument("--base-url", default=os.environ.get(
        "LME_EXTRACT_BASE_URL", extraction.DEFAULT_BASE_URL))
    parser.add_argument("--model", default=os.environ.get(
        "LME_EXTRACT_MODEL", extraction.DEFAULT_MODEL))
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    records = common.load_records(args.data)
    stats = common.load_stats(args.stats)
    ids = split_ids(stats, args.split)
    out_dir = Path(args.out) if args.out else (
        HERE / "runs" / args.split / args.prompt_version)

    if args.clear_stop and (out_dir / "STOP").exists():
        (out_dir / "STOP").unlink()
    if (out_dir / "STOP").exists():
        raise SystemExit("STOP marker present at %s; review and pass --clear-stop" %
                         (out_dir / "STOP"))

    if args.ingest_only:
        summary = extraction.ingest_all(
            records, ids, out_dir, args.prompt_version)
        print(json.dumps({"ok": True, "ingested": len(summary), "out": str(out_dir)},
                         ensure_ascii=False, indent=2))
        return 0

    if args.mock:
        client = extraction.MockClient()
    else:
        api_key = os.environ.get("LME_EXTRACT_API_KEY")
        if not api_key:
            raise SystemExit(
                "LME_EXTRACT_API_KEY is not set; inject it into the run environment "
                "(never paste it into a file or log)")
        client = extraction.OpenRouterClient(
            api_key, base_url=args.base_url, model=args.model, timeout=args.timeout)

    runner = extraction.ExtractionRunner(
        records, ids, out_dir, client,
        prompt_version=args.prompt_version,
        resume=not args.no_resume,
        max_sessions=args.max_sessions,
        question=args.question,
        split=args.split)
    summary = runner.run()
    result = {
        "ok": summary["stop_reason"] not in ("consecutive_failures",),
        "split": args.split,
        "prompt_version": args.prompt_version,
        "out": str(out_dir),
        "channel": getattr(client, "name", "mock"),
        "model": getattr(client, "model", "mock"),
        "interval_seconds": summary["interval_seconds"],
        "calls": summary["calls"],
        "http_429": summary["http_429"],
        "retries": summary["retries"],
        "sessions_ok": summary["sessions_ok"],
        "sessions_skipped": summary["sessions_skipped"],
        "sessions_failed": summary["sessions_failed"],
        "stop_reason": summary["stop_reason"],
    }
    if args.ingest:
        ingested = extraction.ingest_all(records, ids, out_dir, args.prompt_version)
        result["ingested_questions"] = len(ingested)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
