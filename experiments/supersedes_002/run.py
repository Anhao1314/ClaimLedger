"""supersedes_002 runner: candidate v3 edge question on 43 pairs (3 runs),
direction question on the supersedes set (3 runs), and the contract-v2 edge
question on the two corrected pairs (baseline, 3 runs).

    python experiments/supersedes_002/run.py --env-file ~/.config/claimledger/jev.env

Verifies the sha256 manifest first. Asserts the candidate differs from the
contract only in the supersedes criterion. Appends to results/runs.jsonl.
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
EDGE_LABELS = ("supports", "contradicts", "supersedes", "unrelated")
BASELINE_PAIRS = ("sup_d2", "sup_f1")  # corrected in 002; re-run under v2


def verify_manifest() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for name, entry in manifest["files"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            raise SystemExit(f"manifest mismatch: {name} changed after freeze")


def load_questions() -> dict:
    candidate = json.loads((ROOT / "questions.v3.json").read_text(encoding="utf-8"))
    contract = json.loads(
        (REPO / "contracts" / "questions.v2.json").read_text(encoding="utf-8"))
    # integrity: identical except the supersedes criterion and its validation
    for name, entry in contract["questions"].items():
        if name == "edge":
            for key in entry:
                if key in ("criteria", "validation"):
                    continue
                assert candidate["questions"]["edge"][key] == entry[key], key
            for crit, value in entry["criteria"].items():
                if crit != "supersedes":
                    assert candidate["questions"]["edge"]["criteria"][crit] == value
        else:
            assert candidate["questions"][name] == entry, name

    def wire(entry):
        return {"type": entry["type"], "instructions": entry["instructions"],
                "criteria": dict(entry["criteria"])}

    dspec = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
    return {
        "v3": wire(candidate["questions"]["edge"]),
        "v2": wire(contract["questions"]["edge"]),
        "direction": wire(dspec["questions"]["direction"]),
    }


def ask_jev(pair: dict, name: str, question: dict, *, timeout: float) -> dict:
    from chat_distiller import jev
    state = f"Record A (src): {pair['src_text']}\nRecord B (dst): {pair['dst_text']}"
    started = time.monotonic()
    try:
        parsed = jev.ask(state, {name: question}, consent=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {"parse": False, "label": None, "probs": None,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}"[:120]}
    latency = int((time.monotonic() - started) * 1000)
    answer = jev.answer(parsed, name)
    probs = answer.get("probabilities") or {}
    label = max(probs, key=probs.get) if probs else answer.get("choice")
    valid = ("A", "B") if name == "direction" else EDGE_LABELS
    ok = label in valid and all(isinstance(probs.get(l), (int, float))
                                for l in valid)
    if not ok:
        return {"parse": False, "label": None, "probs": None,
                "latency_ms": latency, "error": f"bad answer: {str(answer)[:120]}"}
    return {"parse": True, "label": label,
            "probs": {l: round(float(probs[l]), 4) for l in valid},
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
    pairs = [json.loads(line) for line in
             (ROOT / "pairs.jsonl").read_text().splitlines() if line.strip()]
    by_id = {p["pair_id"]: p for p in pairs}
    questions = load_questions()
    direction_pairs = [p for p in pairs if p["stratum"] == "supersedes"]
    baseline_pairs = [by_id[i] for i in BASELINE_PAIRS]

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
                done.add((row["pair_id"], row["question"], row["run"]))
    slots = ([(p, "v3", r) for r in range(args.runs) for p in pairs] +
             [(p, "direction", r) for r in range(args.runs)
              for p in direction_pairs] +
             [(p, "v2", r) for r in range(args.runs) for p in baseline_pairs])
    slots = [s for s in slots if (s[0]["pair_id"], s[1], s[2]) not in done]
    print(f"pairs: {len(pairs)}, slots: {len(slots)} to run ({len(done)} done)")

    failures = 0
    with open(out, "a", encoding="utf-8") as handle, \
            ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for pair, name, run in slots:
            futures[pool.submit(ask_jev, pair, name, questions[name],
                                timeout=args.timeout)] = (pair, name, run)
        for future in as_completed(futures):
            pair, name, run = futures[future]
            result = None
            for attempt in range(1, args.retries + 1):
                result = (future.result() if attempt == 1 else
                          ask_jev(pair, name, questions[name],
                                  timeout=args.timeout))
                if result["parse"]:
                    break
                time.sleep(min(2 ** attempt, 15))
            if not result["parse"]:
                failures += 1
                print(f"FAIL {pair['pair_id']} {name} run {run}: "
                      f"{result.get('error')}")
                continue
            handle.write(json.dumps({
                "pair_id": pair["pair_id"], "question": name, "run": run,
                "gold": pair["gold"], "stratum": pair["stratum"],
                **result}, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()

    rows = [json.loads(line) for line in out.read_text().splitlines()
            if line.strip()]
    expected = len(pairs) * args.runs + len(direction_pairs) * args.runs \
        + len(baseline_pairs) * args.runs
    print(f"output: {len(rows)} rows ({failures} failures)")
    return 0 if len(rows) == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
