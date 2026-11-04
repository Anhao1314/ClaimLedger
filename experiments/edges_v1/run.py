"""edges_v1 runner: the frozen `edge` question on 120 pairs, 3 runs each.

    python experiments/edges_v1/run.py --env-file ~/.config/claimledger/jev.env

Verifies the sha256 manifest before the first call (pre-registration
discipline). Appends one row per (pair, run) to results/runs.jsonl; safe to
re-run (resumes by skipping completed pair/run slots).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))

RUNS = 3
LABELS = ("supports", "contradicts", "supersedes", "unrelated")


def verify_manifest() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for name, entry in manifest["files"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            raise SystemExit(f"manifest mismatch: {name} changed after freeze")


def load_pairs() -> list:
    return [json.loads(line) for line in
            (ROOT / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_question() -> dict:
    spec = json.loads((ROOT / "questions.v2.json").read_text(encoding="utf-8"))
    entry = spec["questions"]["edge"]
    return {"type": entry["type"], "instructions": entry["instructions"],
            "criteria": dict(entry["criteria"])}


def ask_jev(pair: dict, question: dict, *, timeout: float) -> dict:
    from chat_distiller import jev
    state = f"Record A (src): {pair['src_text']}\nRecord B (dst): {pair['dst_text']}"
    started = time.monotonic()
    try:
        parsed = jev.ask(state, {"edge": question}, consent=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — per-pair isolation, retried below
        return {"parse": False, "label": None, "probs": None,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}"[:120]}
    latency = int((time.monotonic() - started) * 1000)
    answer = jev.answer(parsed, "edge")
    probs = answer.get("probabilities") or {}
    label = max(probs, key=probs.get) if probs else answer.get("choice")
    ok = label in LABELS and all(isinstance(probs.get(l), (int, float))
                                 for l in LABELS)
    if not ok:
        return {"parse": False, "label": None, "probs": None,
                "latency_ms": latency, "error": f"bad answer: {str(answer)[:120]}"}
    return {"parse": True, "label": label,
            "probs": {l: round(float(probs[l]), 4) for l in LABELS},
            "latency_ms": latency, "usage": parsed.get("usage") or {}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="~/.config/claimledger/jev.env")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--runs", type=int, default=RUNS)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    env_path = Path(os.path.expanduser(args.env_file))
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.replace("export", "").strip(),
                                  v.strip().strip("'\""))

    verify_manifest()
    pairs = load_pairs()
    question = load_question()

    from chat_distiller import jev
    if not jev.configured():
        raise SystemExit("TYPESAFE_API_KEY missing")

    out = ROOT / "results" / "runs.jsonl"
    out.parent.mkdir(exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((row["pair_id"], row["run"]))
    slots = [(p, r) for r in range(args.runs) for p in pairs
             if (p["pair_id"], r) not in done]
    print(f"pairs: {len(pairs)}, runs: {args.runs}, done: {len(done)}, "
          f"to run: {len(slots)}")

    failures = 0
    with open(out, "a", encoding="utf-8") as handle, \
            ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for pair, run in slots:
            futures[pool.submit(ask_jev, pair, question,
                                timeout=args.timeout)] = (pair, run)
        for future in as_completed(futures):
            pair, run = futures[future]
            result = None
            for attempt in range(1, args.retries + 1):
                result = future.result() if attempt == 1 else ask_jev(
                    pair, question, timeout=args.timeout)
                if result["parse"]:
                    break
                time.sleep(min(2 ** attempt, 15))
            if not result["parse"]:
                failures += 1
                print(f"FAIL {pair['pair_id']} run {run}: {result.get('error')}")
                continue
            handle.write(json.dumps({
                "pair_id": pair["pair_id"], "run": run,
                "gold": pair["gold"], "in_gold": pair["in_gold"],
                **result}, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()

    rows = [json.loads(line) for line in out.read_text().splitlines()
            if line.strip()]
    print(f"output: {len(rows)} rows ({failures} failures)")
    return 0 if len(rows) == len(pairs) * args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
