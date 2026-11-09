"""e2e_005 runner: the test-repair loop on the 30 executable v8 tasks.

    python experiments/e2e_005/run.py --stage run [--resume] [--workers 4]

Arms:
    R0  MEMORY: (none)        — same one-shot prompt as e2e_002 arm A, plus loop
    R1  the frozen judged brief — same as e2e_002 arm C, plus loop

Loop: attempt 1 one-shot; on failure up to 2 repair attempts with the checker's
own stderr as feedback. Max 3 attempts. One results row per (task, arm).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "e2e_002"

_spec = importlib.util.spec_from_file_location("e2e_002_runner", BASE / "run.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

MAX_ATTEMPTS = 3
FEEDBACK_CHARS = 600


def executable_tasks() -> list:
    out = []
    for d in sorted(p for p in (BASE / "tasks").iterdir() if p.is_dir()):
        meta = json.loads((d / "meta.json").read_text())
        if not meta.get("blocked"):
            out.append(d.name)
    return out


def memory_block(arm: str, task_id: str) -> str:
    if arm == "R0":
        return "(none)"
    return (BASE / "prompts" / "briefs" / f"{task_id}.txt").read_text(
        encoding="utf-8").strip()


def build_prompt(task_id: str, arm: str, previous: str | None = None,
                 feedback: str | None = None) -> tuple:
    meta = base.task_meta(task_id)
    system_file = ("system_natural.md" if meta.get("system") == "natural"
                   else "system.md")
    system = (BASE / "prompts" / system_file).read_text(encoding="utf-8")
    task = (BASE / "tasks" / task_id / "task.md").read_text(encoding="utf-8")
    user = f"MEMORY:\n{memory_block(arm, task_id)}\n\nTASK:\n{task}"
    if previous is not None:
        user += (
            f"\n\nYOUR PREVIOUS ATTEMPT:\n{previous}\n\n"
            f"TEST FEEDBACK (the test failed):\n{feedback[-FEEDBACK_CHARS:]}\n\n"
            "Fix the code so the tests pass. Output only the full corrected "
            "file in a python code block.")
    return system, user


def run_once(task_id: str, system: str, user: str, args, model: str,
             out_dir: Path, attempt: int) -> dict:
    record = {"attempt": attempt, "pass": False, "error": None,
              "latency_ms": None, "prompt_tokens": None,
              "completion_tokens": None, "finish_reason": None}
    response = base.call_api(system, user, model=model,
                             max_tokens=args.max_tokens,
                             base_url=args.base_url, retries=args.retries)
    body = response["body"]
    choice = body["choices"][0]
    content = choice["message"]["content"] or ""
    record["latency_ms"] = response["latency_ms"]
    record["finish_reason"] = choice.get("finish_reason")
    usage = body.get("usage") or {}
    record["prompt_tokens"] = usage.get("prompt_tokens")
    record["completion_tokens"] = usage.get("completion_tokens")
    (out_dir / f"attempt{attempt}.txt").write_text(content, encoding="utf-8")
    record["response"] = content
    meta = base.task_meta(task_id)
    if record["finish_reason"] == "length":
        record["error"] = "truncated"
        return record
    code = base.extract_code(content)
    if not code:
        record["error"] = f"no code block (finish={record['finish_reason']})"
        return record
    with tempfile.TemporaryDirectory(prefix="e2e5_") as tmp_name:
        tmp = Path(tmp_name)
        shutil.copyfile(BASE / "tasks" / task_id / "check.py", tmp / "check.py")
        shutil.copyfile(BASE / "tasks" / task_id / "starter.py",
                        tmp / meta["target"])
        (tmp / meta["target"]).write_text(code, encoding="utf-8")
        passed, output = base.run_check(tmp)
    record["pass"] = passed
    record["check_output"] = output
    return record


def run_job(job, args, model, results_path, lock, budget) -> dict:
    task_id, arm = job
    out_dir = ROOT / "results" / task_id / arm
    out_dir.mkdir(parents=True, exist_ok=True)
    attempts = []
    previous = None
    feedback = None
    final_pass = False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if not budget.take():
            break
        system, user = build_prompt(task_id, arm, previous, feedback)
        (out_dir / f"prompt{attempt}.txt").write_text(
            f"SYSTEM:\n{system}\n\nUSER:\n{user}\n", encoding="utf-8")
        rec = run_once(task_id, system, user, args, model, out_dir, attempt)
        attempts.append(rec)
        if rec["pass"]:
            final_pass = True
            break
        previous = rec.get("response") or ""
        feedback = rec.get("check_output") or rec.get("error") or ""
    row = {"task": task_id, "arm": arm, "model": model,
           "final_pass": final_pass, "iterations": len(attempts),
           "attempts": [{k: v for k, v in a.items() if k != "response"}
                        for a in attempts]}
    with lock:
        with open(results_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{task_id:24} {arm} {'PASS' if final_pass else 'fail'} "
              f"iter={len(attempts)}", flush=True)
    time.sleep(args.sleep)
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="run", choices=("run",))
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--max-calls", type=int, default=240)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    base.load_env(Path("~/.config/claimledger/deepseek.env").expanduser())
    base.load_env(Path("~/.config/claimledger/jev.env").expanduser())
    model = args.model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    results_path = ROOT / "results" / "results.jsonl"
    results_path.parent.mkdir(exist_ok=True)
    done = set()
    if args.resume and results_path.exists():
        for line in results_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((row["task"], row["arm"]))
    tasks = executable_tasks()
    jobs = [(t, a) for t in tasks for a in ("R0", "R1") if (t, a) not in done]
    if args.shuffle:
        random.Random(args.seed).shuffle(jobs)
    lock = __import__("threading").Lock()
    budget = base.CallBudget(args.max_calls)
    print(f"tasks: {len(tasks)}, jobs: {len(jobs)}")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_job, job, args, model, results_path,
                               lock, budget) for job in jobs]
        for future in as_completed(futures):
            future.result()
    rows = [json.loads(l) for l in results_path.read_text().splitlines()
            if l.strip()]
    print(f"rows: {len(rows)} / {len(tasks) * 2}")
    return 0 if len(rows) >= len(tasks) * 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())