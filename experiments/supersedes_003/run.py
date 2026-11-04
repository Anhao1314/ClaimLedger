"""supersedes_003 runner: the cascade experiment.

    python experiments/supersedes_003/run.py --env-file ~/.config/claimledger/jev.env

Stage 1: contract-v2 `edge` question on all 43 pairs x 3 runs.
Stage 2: candidate `replacement` question on every pair whose edge argmax is
         `contradicts` in ANY run (the union) x 3 runs.
Stage 3: `direction` question on the supersedes set x 3 runs.
Verifies the manifest; asserts the edge question is byte-identical to the
contract. Appends to results/runs.jsonl; safe to re-run.
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


def verify_manifest() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for name, entry in manifest["files"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            raise SystemExit(f"manifest mismatch: {name} changed after freeze")


def load_questions() -> dict:
    from jev_first import contracts
    edge = contracts.edge_question()
    product = json.loads(
        (REPO / "contracts" / "questions.v2.json").read_text(encoding="utf-8"))
    expected = product["questions"]["edge"]
    assert (edge == {"type": expected["type"],
                     "instructions": expected["instructions"],
                     "criteria": expected["criteria"]}), "contract drift"
    dspec = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
    entry = dspec["questions"]["replacement"]
    replacement = {"type": entry["type"], "instructions": entry["instructions"],
                   "criteria": dict(entry["criteria"])}
    dirspec = json.loads((ROOT / "direction.json").read_text(encoding="utf-8"))
    dentry = dirspec["questions"]["direction"]
    direction = {"type": dentry["type"], "instructions": dentry["instructions"],
                 "criteria": dict(dentry["criteria"])}
    return {"edge": edge, "replacement": replacement, "direction": direction}


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
    valid = ("A", "B") if name == "direction" else (
        ("yes", "no") if name == "replacement" else EDGE_LABELS)
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

    def plan(question_name: str, pool: list) -> list:
        return [(p, question_name, r) for r in range(args.runs) for p in pool]

    edge_slots = [s for s in plan("edge", pairs)
                  if (s[0]["pair_id"], "edge", s[2]) not in done]

    def run_slots(slots: list, questions_map: dict) -> int:
        if not slots:
            return 0
        failures = 0
        with open(out, "a", encoding="utf-8") as handle, \
                ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {}
            for pair, name, run in slots:
                futures[pool.submit(ask_jev, pair, name, questions_map[name],
                                    timeout=args.timeout)] = (pair, name, run)
            for future in as_completed(futures):
                pair, name, run = futures[future]
                result = None
                for attempt in range(1, args.retries + 1):
                    result = (future.result() if attempt == 1 else
                              ask_jev(pair, name, questions_map[name],
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
        return failures

    failures = run_slots(edge_slots, questions)
    print(f"edge: {len(pairs) * args.runs - len(edge_slots)} done, "
          f"{len(edge_slots)} run, {failures} failures")

    # stage 2: the contradicted union across runs
    edge_rows = [json.loads(line) for line in out.read_text().splitlines()
                 if line.strip() and json.loads(line)["question"] == "edge"]
    contradicted = sorted({r["pair_id"] for r in edge_rows
                           if r["label"] == "contradicts"})
    rep_slots = [s for s in plan("replacement", [by_id[p] for p in contradicted])
                 if (s[0]["pair_id"], "replacement", s[2]) not in done]
    failures += run_slots(rep_slots, questions)
    print(f"replacement subset: {len(contradicted)} pairs, "
          f"{len(rep_slots)} slots run")

    # stage 3: direction on the supersedes set
    sup_pairs = [p for p in pairs if p["stratum"] == "supersedes"]
    dir_slots = [s for s in plan("direction", sup_pairs)
                 if (s[0]["pair_id"], "direction", s[2]) not in done]
    failures += run_slots(dir_slots, questions)
    print(f"direction: {len(sup_pairs)} pairs, {len(dir_slots)} slots run")

    rows = [json.loads(line) for line in out.read_text().splitlines()
            if line.strip()]
    expected = len(pairs) * args.runs + len(contradicted) * args.runs \
        + len(sup_pairs) * args.runs
    print(f"output: {len(rows)} rows (expected {expected}, {failures} failures)")
    return 0 if len(rows) == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
