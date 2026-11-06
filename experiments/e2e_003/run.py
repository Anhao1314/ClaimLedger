"""e2e_003 runner: E (pure RAG) and F (composition) arms + the cross-lingual
probe, on the inherited e2e_002 v8 corpus.

Stages:
    python experiments/e2e_003/run.py --stage briefs    # JEV: freeze F and
        C-probe briefs (deterministic; temperature 0; cache_f.jsonl)
    python experiments/e2e_003/run.py --stage generate  # DeepSeek: 3 runs ×
        {E, F} × 48 tasks + 3 runs × C × 8 probes (C on v8 tasks is inherited)

memory_block:
    E  — cosine top-5 records (frozen vectors), packed under the 2048-byte
         budget, rendered in the same "- text" format as C/B
    F  — prompts_f/<task>.txt (frozen from the judge over union(lexical,
         embedding top-6) candidates)
    C  — v8 tasks: inherited e2e_002 frozen briefs; probes: prompts_c_probe/
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "e2e_002"
sys.path.insert(0, str(ROOT.parents[1]))

_spec = importlib.util.spec_from_file_location(
    "e2e_002_runner", BASE / "run.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

from jev_first import judge as jev_judge  # noqa: E402
from jev_first.brief import render_brief  # noqa: E402
from jev_first.cache import Cache  # noqa: E402
from jev_first.records import RecordStore  # noqa: E402
from jev_first.select import select_candidates  # noqa: E402

RUNS = 3
BUDGET_BYTES = 2048
TOP_E = 5
TOP_F = 6
PROBE_STRATUM = "cross_lingual"


def load_env_both() -> None:
    base.load_env(Path("~/.config/claimledger/deepseek.env").expanduser())
    base.load_env(Path("~/.config/claimledger/jev.env").expanduser())


def load_vectors() -> tuple:
    data = np.load(ROOT / "embeddings.npz", allow_pickle=False)
    rec_ids = [str(x) for x in data["record_ids"]]
    rec_vecs = data["record_vecs"]
    task_ids = [str(x) for x in data["task_ids"]]
    task_vecs = data["task_vecs"]
    return rec_ids, rec_vecs, task_ids, task_vecs


def task_text(task_id: str) -> str:
    for d in (BASE / "tasks", ROOT / "probe_tasks"):
        p = d / task_id / "task.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise KeyError(task_id)


def all_task_ids() -> list:
    ids = [p.name for p in sorted((BASE / "tasks").iterdir()) if p.is_dir()]
    ids += [p.name for p in sorted((ROOT / "probe_tasks").iterdir())
            if p.is_dir()]
    return ids


def is_probe(task_id: str) -> bool:
    return (ROOT / "probe_tasks" / task_id).exists()


def embed_top(vectors, task_id: str, k: int):
    rec_ids, rec_vecs, task_ids, task_vecs = vectors
    qi = task_ids.index(task_id)
    sims = rec_vecs @ task_vecs[qi]
    order = np.argsort(-sims)[:k]
    return [(rec_ids[i], float(sims[i])) for i in order]


def block_E(task_id: str, vectors) -> str:
    rec_ids, rec_vecs, task_ids, task_vecs = vectors
    hits = embed_top(vectors, task_id, TOP_E)
    by_id = {r["record_id"]: r["text"] for r in
             RecordStore(BASE / "memory" / "records.jsonl").load()}
    lines, used = [], 0
    for rid, _sim in hits:
        line = "- " + by_id[rid]
        size = len(line.encode("utf-8")) + 1
        if used + size > BUDGET_BYTES:
            break
        lines.append(line)
        used += size
    return "\n".join(lines) if lines else "(no record passed the similarity cut)"


def candidates_f(task_id: str, task: str, records: list, vectors) -> list:
    lexical, _stats = select_candidates(records, task, limit=6)
    chosen = [r["record_id"] for r in lexical]
    chosen_set = set(chosen)
    for rid, _sim in embed_top(vectors, task_id, TOP_F):
        if rid not in chosen_set:
            chosen.append(rid)
            chosen_set.add(rid)
        if len(chosen) >= 6:
            break
    by_id = {r["record_id"]: r for r in records}
    return [by_id[rid] for rid in chosen]


def freeze_briefs(args) -> int:
    load_env_both()
    vectors = load_vectors()
    records = RecordStore(BASE / "memory" / "records.jsonl").load()
    cache = Cache(ROOT / "cache_f.jsonl")
    out_f = ROOT / "prompts_f"
    out_c = ROOT / "prompts_c_probe"
    out_f.mkdir(exist_ok=True)
    out_c.mkdir(exist_ok=True)
    log_path = ROOT / "f_judgments.jsonl"
    rows = []
    for task_id in all_task_ids():
        task = task_text(task_id)
        # F: union candidates
        cands = candidates_f(task_id, task, records, vectors)
        j = jev_judge(task, cands, budget_bytes=BUDGET_BYTES,
                      on_error="review", cache=cache)
        brief_f = render_brief(j)["text"]
        (out_f / f"{task_id}.txt").write_text(brief_f, encoding="utf-8")
        rows.append({"task": task_id, "arm": "F", "requests": j.requests,
                     "degraded": j.degraded,
                     "judgment_hash": j.input_hash,
                     "edges": [e.to_dict() for e in j.edges]})
        # C: lexical-only candidates — only needed for probe tasks (v8 C
        # briefs are inherited frozen from e2e_002)
        if is_probe(task_id):
            lexical, _stats = select_candidates(records, task, limit=6)
            j2 = jev_judge(task, lexical, budget_bytes=BUDGET_BYTES,
                           on_error="review", cache=cache)
            brief_c = render_brief(j2)["text"]
            (out_c / f"{task_id}.txt").write_text(brief_c, encoding="utf-8")
            rows.append({"task": task_id, "arm": "C", "requests": j2.requests,
                         "degraded": j2.degraded,
                         "judgment_hash": j2.input_hash, "edges": []})
        print(f"brief {task_id}: F {len(brief_f)}B, "
              f"candidates={len(cands)}")
    with open(log_path, "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"froze {len(rows)} briefs → prompts_f/ + prompts_c_probe/")
    return 0


def task_meta(task_id: str) -> dict:
    for d in (BASE / "tasks", ROOT / "probe_tasks"):
        p = d / task_id / "meta.json"
        if p.exists():
            return json.loads(p.read_text())
    raise KeyError(task_id)


def build_prompt(task_id: str, arm: str, vectors) -> tuple:
    meta = task_meta(task_id)
    system_file = ("system_natural.md" if meta.get("system") == "natural"
                   else "system.md")
    system = (BASE / "prompts" / system_file).read_text(encoding="utf-8")
    task = task_text(task_id)
    if arm == "E":
        block = block_E(task_id, vectors)
    elif arm == "F":
        block = (ROOT / "prompts_f" / f"{task_id}.txt").read_text("utf-8").strip()
    elif arm == "C":
        if is_probe(task_id):
            block = (ROOT / "prompts_c_probe" / f"{task_id}.txt").read_text("utf-8").strip()
        else:
            block = base.memory_block("C", task_id)
    else:
        raise ValueError(arm)
    return system, f"MEMORY:\n{block}\n\nTASK:\n{task}"


def check_dir(task_id: str) -> Path:
    return (ROOT / "probe_tasks" / task_id if is_probe(task_id)
            else BASE / "tasks" / task_id)


def run_job(job, vectors, args, model, results_path, lock, budget) -> dict:
    task_id, arm, run = job
    meta = task_meta(task_id)
    system, user = build_prompt(task_id, arm, vectors)
    out_dir = ROOT / "results" / task_id / arm / f"run{run}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompt.txt").write_text(
        f"SYSTEM:\n{system}\n\nUSER:\n{user}\n", encoding="utf-8")
    record = {"task": task_id, "arm": arm, "run": run, "model": model,
              "prompt_tokens": None, "completion_tokens": None,
              "latency_ms": None, "pass": False, "error": None,
              "attempts": None, "finish_reason": None, "length_retries": 0}
    try:
        token_budget = args.max_tokens
        content = ""
        for length_try in range(2):
            if not budget.take():
                record["error"] = "max_calls reached"
                break
            response = base.call_api(system, user, model=model,
                                     max_tokens=token_budget,
                                     base_url=args.base_url,
                                     retries=args.retries)
            body = response["body"]
            choice = body["choices"][0]
            content = choice["message"]["content"]
            record["latency_ms"] = response["latency_ms"]
            record["finish_reason"] = choice.get("finish_reason")
            usage = body.get("usage") or {}
            record["prompt_tokens"] = usage.get("prompt_tokens")
            record["completion_tokens"] = usage.get("completion_tokens")
            (out_dir / f"attempt{length_try + 1}.txt").write_text(
                content, encoding="utf-8")
            if record["finish_reason"] != "length" or length_try == 1:
                break
            record["length_retries"] += 1
            token_budget = min(token_budget * 2, 16000)
        if not record["error"]:
            (out_dir / "response.txt").write_text(content, encoding="utf-8")
            if record["finish_reason"] == "length":
                record["error"] = "truncated after length retry"
            code = base.extract_code(content)
            with tempfile.TemporaryDirectory(prefix="e2e3_") as tmp_name:
                tmp = Path(tmp_name)
                shutil.copyfile(check_dir(task_id) / "check.py", tmp / "check.py")
                if meta["target"]:
                    shutil.copyfile(check_dir(task_id) / "starter.py",
                                    tmp / meta["target"])
                    if not code:
                        record["error"] = (
                            f"no code block (finish={record['finish_reason']})")
                    else:
                        (tmp / meta["target"]).write_text(code, encoding="utf-8")
                else:
                    (tmp / "response.txt").write_text(content, encoding="utf-8")
                if not record["error"]:
                    passed, output = base.run_check(tmp)
                    record["pass"] = passed
                    record["check_output"] = output
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"{type(exc).__name__}: {exc}"
    with lock:
        with open(results_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"{task_id:24} {arm} run{run} "
              f"{'PASS' if record['pass'] else 'fail'} {record['error'] or ''}",
              flush=True)
    time.sleep(args.sleep)
    return record


def generate(args) -> int:
    load_env_both()
    model = args.model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    vectors = load_vectors()
    results_path = ROOT / "results" / "results.jsonl"
    results_path.parent.mkdir(exist_ok=True)
    done = set()
    if args.resume and results_path.exists():
        for line in results_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                error = str(row.get("error") or "")
                if row.get("pass") or not error or error.startswith("no code block"):
                    done.add((row["task"], row["arm"], row["run"]))
    jobs = []
    for task_id in all_task_ids():
        for arm in ("E", "F"):
            for run in range(1, RUNS + 1):
                if (task_id, arm, run) not in done:
                    jobs.append((task_id, arm, run))
    for task_id in all_task_ids():
        if is_probe(task_id):
            for run in range(1, RUNS + 1):
                if (task_id, "C", run) not in done:
                    jobs.append((task_id, "C", run))
    if args.shuffle:
        random.Random(args.seed).shuffle(jobs)
    lock = threading.Lock()
    budget = base.CallBudget(args.max_calls)
    print(f"jobs: {len(jobs)} to run")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_job, job, vectors, args, model,
                               results_path, lock, budget) for job in jobs]
        for future in as_completed(futures):
            future.result()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("briefs", "generate"), required=True)
    parser.add_argument("--env-file", default="~/.config/claimledger/deepseek.env")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--runs", type=int, default=RUNS)
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--max-calls", type=int, default=400)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    load_env_both()
    if args.stage == "briefs":
        return freeze_briefs(args)
    return generate(args)


if __name__ == "__main__":
    raise SystemExit(main())
