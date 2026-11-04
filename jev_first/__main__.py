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
from dataclasses import replace
from pathlib import Path

from . import log
from . import proposals as proposal_log
from .cache import Cache
from .judge import DEFAULT_BUDGET_BYTES, judge
from .outcomes import append_outcome
from .outcomes import read as read_outcomes
from .records import RecordStore, find_near_duplicate


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

    p_propose = sub.add_parser("propose", help="propose a record for human confirmation")
    p_propose.add_argument("--store", required=True)
    p_propose.add_argument("--text", required=True)
    p_propose.add_argument("--source", required=True)
    p_propose.add_argument("--scope")
    p_propose.add_argument("--at")
    p_propose.add_argument("--proposals", help="proposals.jsonl path")

    p_proposals = sub.add_parser("proposals", help="list pending proposals")
    p_proposals.add_argument("--store", required=True)
    p_proposals.add_argument("--proposals", help="proposals.jsonl path")

    p_confirm = sub.add_parser("confirm", help="confirm a proposal into a record")
    p_confirm.add_argument("--store", required=True)
    p_confirm.add_argument("--proposal-id", required=True)
    p_confirm.add_argument("--by", default="cli-human")
    p_confirm.add_argument("--proposals", help="proposals.jsonl path")

    p_reject = sub.add_parser("reject", help="reject a proposal")
    p_reject.add_argument("--proposals", required=True)
    p_reject.add_argument("--proposal-id", required=True)
    p_reject.add_argument("--by", default="cli-human")

    p_edges = sub.add_parser("edges", help="list pending edge proposals")
    p_edges.add_argument("--edges", required=True, help="edges.jsonl path")

    p_edge_confirm = sub.add_parser(
        "edge-confirm", help="confirm a proposed graph edge")
    p_edge_confirm.add_argument("--edges", required=True, help="edges.jsonl path")
    p_edge_confirm.add_argument("--edge-id", required=True)
    p_edge_confirm.add_argument("--by", default="cli-human")

    p_edge_reject = sub.add_parser("edge-reject", help="reject a proposed graph edge")
    p_edge_reject.add_argument("--edges", required=True, help="edges.jsonl path")
    p_edge_reject.add_argument("--edge-id", required=True)
    p_edge_reject.add_argument("--by", default="cli-human")

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
    p_calibrate.add_argument("--store", help="records.jsonl; enables the per-author breakdown")
    p_calibrate.add_argument("--action", default="admit")

    p_audit = sub.add_parser("audit", help="summarize the judgment history")
    p_audit.add_argument("--log", required=True)
    p_audit.add_argument("--record-id", help="only judgments touching this record")

    p_agent_reg = sub.add_parser("agent-register", help="register an agent or human identity")
    p_agent_reg.add_argument("--dir", default="~/.jev-memory")
    p_agent_reg.add_argument("--name", required=True)
    p_agent_reg.add_argument("--kind", choices=("agent", "human"), default="agent")

    p_agent_list = sub.add_parser("agent-list", help="list registered identities")
    p_agent_list.add_argument("--dir", default="~/.jev-memory")

    p_console = sub.add_parser("console", help="local single-user memory console (web)")
    p_console.add_argument("--store", required=True)
    p_console.add_argument("--dir", default="~/.jev-memory",
                           help="directory for log/cache/outcomes")
    p_console.add_argument("--port", type=int, default=8766)

    args = parser.parse_args(argv)

    if args.command == "record":
        store = RecordStore(args.store)
        records = store.load()
        existing = find_near_duplicate(records, args.text, scope=args.scope)
        if existing:
            record, similarity = existing
            print(json.dumps({"record": record, "created": False,
                              "duplicate": "near", "similarity": similarity},
                             ensure_ascii=False, indent=2))
            return 0
        record = store.append(args.text, args.source,
                              at=args.at, scope=args.scope)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0

    if args.command == "propose":
        p_path = args.proposals or str(Path(args.store).parent / "proposals.jsonl")
        records = RecordStore(args.store).load()
        existing = find_near_duplicate(records, args.text, scope=args.scope)
        if existing:
            print(json.dumps({"created": False, "duplicate": "record",
                              "record": existing[0],
                              "similarity": existing[1]},
                             ensure_ascii=False, indent=2))
            return 0
        pending = proposal_log.pending(p_path)
        candidates = [{"record_id": p["proposal_id"], "text": p["text"],
                       "scope": p.get("scope")} for p in pending]
        near = find_near_duplicate(candidates, args.text, scope=args.scope)
        if near:
            match = next(p for p in pending
                         if p["proposal_id"] == near[0]["record_id"])
            print(json.dumps({"created": False, "duplicate": "pending",
                              "proposal": match, "similarity": near[1]},
                             ensure_ascii=False, indent=2))
            return 0
        try:
            proposal = proposal_log.propose(
                p_path, text=args.text, source=args.source,
                scope=args.scope, at=args.at)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"created": True, "status": "pending",
                          "proposal": proposal}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "proposals":
        p_path = args.proposals or str(Path(args.store).parent / "proposals.jsonl")
        print(json.dumps(proposal_log.pending(p_path),
                         ensure_ascii=False, indent=2))
        return 0

    if args.command == "confirm":
        p_path = args.proposals or str(Path(args.store).parent / "proposals.jsonl")
        proposal = proposal_log.get(p_path, args.proposal_id)
        if proposal is None:
            print(f"unknown proposal: {args.proposal_id}", file=sys.stderr)
            return 2
        if proposal_log.decision_for(p_path, args.proposal_id) is not None:
            print(f"proposal already decided: {args.proposal_id}", file=sys.stderr)
            return 2
        store = RecordStore(args.store)
        existing = find_near_duplicate(store.load(), str(proposal["text"]),
                                       scope=proposal.get("scope"))
        if existing:
            record, created = existing[0], False
        else:
            record = store.append(str(proposal["text"]),
                                  str(proposal["source"]),
                                  scope=proposal.get("scope"))
            created = True
        try:
            event = proposal_log.decide(
                p_path, args.proposal_id, decision="confirmed", by=args.by,
                record_id=record["record_id"])
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"decision": event, "record": record,
                          "created": created}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "reject":
        try:
            event = proposal_log.decide(
                args.proposals, args.proposal_id, decision="rejected",
                by=args.by)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(event, ensure_ascii=False, indent=2))
        return 0

    if args.command == "edges":
        from . import edges as edge_log
        rows = edge_log.pending(args.edges)
        try:
            verified = edge_log.verify(args.edges)
        except ValueError as exc:
            print(f"edge log corrupt: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"verified_events": verified,
                          "pending_count": len(rows), "pending": rows},
                         ensure_ascii=False, indent=2))
        return 0

    if args.command in ("edge-confirm", "edge-reject"):
        from . import edges as edge_log
        try:
            event = edge_log.decide_edge(
                args.edges, args.edge_id,
                decision="confirmed" if args.command == "edge-confirm"
                else "rejected", by=args.by)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(event, ensure_ascii=False, indent=2))
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
        judgment = replace(judgment, selection=stats)
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
        judgment = replace(judgment, selection=stats)
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
        records = RecordStore(args.store).load() if args.store else None
        report = calibrate(log.read(args.log), read_outcomes(args.outcomes),
                           action=args.action, records=records)
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
        if report.get("by_author"):
            print(f"\n{'author':24} {'n':>4} {'upheld':>7} {'Brier':>7}")
            for author, data in report["by_author"].items():
                print(f"{author:24} {data['n']:>4} {data['upheld_rate']:>7} {data['brier']:>7}")
        return 0

    if args.command == "audit":
        from .audit import for_record, summarize
        if args.record_id:
            for item in for_record(args.log, args.record_id, reader=log.read):
                print(json.dumps(item, ensure_ascii=False))
        else:
            print(json.dumps(summarize(args.log, reader=log.read),
                             ensure_ascii=False, indent=2))
        return 0

    if args.command == "agent-register":
        from . import agents as agent_registry
        path = Path(args.dir).expanduser() / "agents.jsonl"
        entry = agent_registry.append_agent(path, name=args.name, kind=args.kind)
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return 0

    if args.command == "agent-list":
        from . import agents as agent_registry
        path = Path(args.dir).expanduser() / "agents.jsonl"
        rows = agent_registry.read(path)
        for row in rows:
            print(f"{row['agent_id']}  {row['name']:<24} {row['kind']:<6} {row['created_at']}")
        print(f"{len(rows)} identities, chain verified: {agent_registry.verify(path) == len(rows)}")
        return 0

    if args.command == "console":
        from .web import main as console_main
        return console_main(["--store", args.store, "--dir", args.dir,
                             "--port", str(args.port)])

    parser.print_usage()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())