"""Jev-first memory: CLI.

    python -m jev_first record --store s.jsonl --text "..." --source agent
    python -m jev_first judge  --store s.jsonl --task "..." [--budget 2048]
    python -m jev_first verify --store s.jsonl
    python -m jev_first verify-log --log d.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import log
from .cache import Cache
from .judge import DEFAULT_BUDGET_BYTES, judge
from .outcomes import append_outcome
from .outcomes import read as read_outcomes
from .records import RecordStore


def _print_decision(judgment, sealed=None) -> None:
    body = judgment.to_dict()
    print(f"task      : {judgment.task}")
    print(f"model     : {judgment.model}   qset: {judgment.question_set_version}"
          f"   policy: {judgment.policy['version']}"
          f"   cached: {judgment.cached}   degraded: {judgment.degraded}")
    print(f"latency   : {judgment.latency_ms} ms   requests: {judgment.requests}"
          f"   pairs: {judgment.pair_checks}   tokens: {judgment.usage}")
    print(f"conflicts : {judgment.conflicts or 'none'}   governing: {judgment.governing}")
    print()
    print(f"{'record':18} {'action':8} {'p(admit)':>9} {'conf':>5} {'gov':4} {'cf':4} {'in':3}")
    print("-" * 62)
    for entry in sorted(judgment.entries, key=lambda e: (e.p_admit or 0), reverse=True):
        print(f"{entry.record_id:18} {entry.action:8} "
              f"{entry.p_admit if entry.p_admit is not None else '':>9} "
              f"{entry.confidence if entry.confidence is not None else '':>5} "
              f"{'yes' if entry.governing else '':4} "
              f"{'yes' if entry.conflicted else '':4} "
              f"{'yes' if entry.included else 'no':3}")
    print("-" * 62)
    print(f"bytes {judgment.used_bytes}/{judgment.budget_bytes}   omitted {judgment.omitted}")
    if sealed is not None:
        print(f"sealed     : {sealed['judgment_hash'][:16]}…  "
              f"prev {sealed['prev_hash'][:16]}…")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="jev_first")
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="append one record")
    p_record.add_argument("--store", required=True)
    p_record.add_argument("--text", required=True)
    p_record.add_argument("--source", required=True)
    p_record.add_argument("--scope")
    p_record.add_argument("--at")

    p_judge = sub.add_parser("judge", help="judge pre-selected records against a task")
    p_judge.add_argument("--store", required=True)
    p_judge.add_argument("--task", required=True)
    p_judge.add_argument("--budget", type=int, default=DEFAULT_BUDGET_BYTES)
    p_judge.add_argument("--model")
    p_judge.add_argument("--cache", help="judgment cache path")
    p_judge.add_argument("--no-cache", action="store_true")
    p_judge.add_argument("--log", help="sealed judgment log path")
    p_judge.add_argument("--on-error", choices=("raise", "review"), default="review")

    p_decide = sub.add_parser("decide", help="select candidates from the store, then judge")
    p_decide.add_argument("--store", required=True)
    p_decide.add_argument("--task", required=True)
    p_decide.add_argument("--scope", help="restrict candidates to a scope")
    p_decide.add_argument("--limit", type=int, default=6)
    p_decide.add_argument("--budget", type=int, default=DEFAULT_BUDGET_BYTES)
    p_decide.add_argument("--model")
    p_decide.add_argument("--cache", help="judgment cache path")
    p_decide.add_argument("--no-cache", action="store_true")
    p_decide.add_argument("--log", help="sealed judgment log path")
    p_decide.add_argument("--on-error", choices=("raise", "review"), default="review")

    p_verify = sub.add_parser("verify", help="verify the record hash chain")
    p_verify.add_argument("--store", required=True)

    p_vlog = sub.add_parser("verify-log", help="verify the judgment log chain")
    p_vlog.add_argument("--log", required=True)

    p_brief = sub.add_parser("brief", help="select + judge, then render the agent-facing brief")
    p_brief.add_argument("--store", required=True)
    p_brief.add_argument("--task", required=True)
    p_brief.add_argument("--scope")
    p_brief.add_argument("--limit", type=int, default=6)
    p_brief.add_argument("--budget", type=int, default=DEFAULT_BUDGET_BYTES)
    p_brief.add_argument("--cache", help="judgment cache path")
    p_brief.add_argument("--no-cache", action="store_true")

    p_outcome = sub.add_parser("outcome", help="record how a judgment turned out")
    p_outcome.add_argument("--outcomes", required=True, help="outcomes.jsonl path")
    p_outcome.add_argument("--log", required=True, help="sealed judgment log")
    p_outcome.add_argument("--record-id", required=True)
    p_outcome.add_argument("--verdict", required=True,
                           choices=("upheld", "overturned", "unclear"))
    p_outcome.add_argument("--by", required=True)
    p_outcome.add_argument("--note", default="")
    p_outcome.add_argument("--last", action="store_true",
                           help="attach to the most recent judgment in the log")

    p_calibrate = sub.add_parser("calibrate", help="score the judge against outcomes")
    p_calibrate.add_argument("--log", required=True)
    p_calibrate.add_argument("--outcomes", required=True)
    p_calibrate.add_argument("--action", default="admit")

    p_audit = sub.add_parser("audit", help="summarize the judgment history")
    p_audit.add_argument("--log", required=True)
    p_audit.add_argument("--record-id", help="only judgments touching this record")

    p_console = sub.add_parser("console", help="local single-user memory console (web)")
    p_console.add_argument("--store", required=True)
    p_console.add_argument("--dir", default="~/.jev-memory",
                           help="directory for log/cache/outcomes")
    p_console.add_argument("--port", type=int, default=8766)

    args = parser.parse_args(argv)

    if args.command == "record":
        record = RecordStore(args.store).append(args.text, args.source,
                                                at=args.at, scope=args.scope)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0

    if args.command == "judge":
        records = RecordStore(args.store).load()
        if not records:
            print("store is empty", file=sys.stderr)
            return 2
        cache = None if args.no_cache else Cache(args.cache or args.store + ".cache.jsonl")
        judgment = judge(args.task, records, budget_bytes=args.budget,
                         model=args.model, on_error=args.on_error, cache=cache)
        sealed = None
        if args.log:
            sealed = log.append_judgment(args.log, judgment.to_dict())
        _print_decision(judgment, sealed)
        return 0

    if args.command == "decide":
        from .select import select_candidates
        records = RecordStore(args.store).load()
        if not records:
            print("store is empty", file=sys.stderr)
            return 2
        candidates, stats = select_candidates(records, args.task,
                                              scope=args.scope, limit=args.limit)
        print(f"selection: {stats}")
        if not candidates:
            print("no candidates in scope", file=sys.stderr)
            return 2
        cache = None if args.no_cache else Cache(args.cache or args.store + ".cache.jsonl")
        judgment = judge(args.task, candidates, budget_bytes=args.budget,
                         model=args.model, on_error=args.on_error, cache=cache)
        sealed = None
        if args.log:
            sealed = log.append_judgment(args.log, judgment.to_dict())
        _print_decision(judgment, sealed)
        return 0

    if args.command == "verify":
        count = len(RecordStore(args.store).load())
        print(f"ok: {count} records, chain verified")
        return 0

    if args.command == "verify-log":
        count = log.verify(args.log)
        print(f"ok: {count} judgments, chain verified")
        return 0

    if args.command == "brief":
        from .brief import render_brief
        from .select import select_candidates
        records = RecordStore(args.store).load()
        candidates, stats = select_candidates(records, args.task,
                                              scope=args.scope, limit=args.limit)
        cache = None if args.no_cache else Cache(args.cache or args.store + ".cache.jsonl")
        judgment = judge(args.task, candidates, budget_bytes=args.budget,
                         on_error="review", cache=cache)
        brief = render_brief(judgment)
        print(brief["text"])
        print(f"\n[brief: {brief['bytes']} bytes · {brief['admitted']} admitted · "
              f"warnings {brief['warnings'] or 'none'} · input {brief['input_hash'][:16]}…]")
        return 0

    if args.command == "outcome":
        rows = log.read(args.log)
        if args.last:
            if not rows:
                print("judgment log is empty", file=sys.stderr)
                return 2
            judgment_hash = rows[-1]["judgment_hash"]
        else:
            matches = [r["judgment_hash"] for r in rows
                       if r.get("judgment_hash") and any(
                           e.get("record_id") == args.record_id
                           for e in r.get("entries", []))]
            if not matches:
                print(f"no judgment in the log touches {args.record_id}",
                      file=sys.stderr)
                return 2
            judgment_hash = matches[-1]
        outcome = append_outcome(args.outcomes, judgment_hash=judgment_hash,
                                 record_id=args.record_id, verdict=args.verdict,
                                 by=args.by, note=args.note)
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "calibrate":
        from .calibration import calibrate
        report = calibrate(log.read(args.log), read_outcomes(args.outcomes),
                           action=args.action)
        print(f"action '{report['action']}': {report['n_scored']} scored of "
              f"{report['n_outcomes']} outcomes "
              f"(orphans {report['orphans']}, unsupported {report['unsupported']})")
        print(f"overall upheld rate: {report['overall_upheld_rate']}   "
              f"Brier: {report['brier']}")
        print(f"{'bucket':14} {'n':>4} {'upheld':>7}")
        for bucket, data in report["buckets"].items():
            if data["n"]:
                rate = (f"{data['upheld_rate']:.2f}"
                        if data["upheld_rate"] is not None else "-")
                print(f"{bucket:14} {data['n']:>4} {rate:>7}")
        for model, data in report["by_model"].items():
            print(f"model {model}: n={data['n']} upheld {data['upheld_rate']}")
        return 0

    if args.command == "audit":
        from .audit import for_record, summarize
        if args.record_id:
            for item in for_record(args.log, args.record_id):
                print(json.dumps(item, ensure_ascii=False))
        else:
            print(json.dumps(summarize(args.log, reader=log.read),
                             ensure_ascii=False, indent=2))
        return 0

    if args.command == "console":
        from .web import main as console_main
        return console_main(["--store", args.store, "--dir", args.dir,
                             "--port", str(args.port)])

    parser.print_usage()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())