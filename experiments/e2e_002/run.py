"""Run the e2e_002 memory experiment.

Pilot:
    python experiments/e2e_002/run.py \
      --env-file ~/.config/claimledger/deepseek.env \
      --runs 1

Full run (after expanding the task set):
    python experiments/e2e_002/run.py --runs 3 --shuffle --seed 7

The API key is read from an env file or the process environment. No key is
written to the repo. Every prompt/response is saved under results/.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CODE_RE = re.compile(r"```(?:python3?|py)?\s*\n(.*?)(?:```|$)", re.S)
RETRYABLE = (429, 500, 502, 503, 504)


def load_env(path: Path) -> None:
    text = path.expanduser().read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freeze(allow: bool) -> None:
    path = ROOT / "freeze.json"
    if not path.exists():
        if allow:
            print("warning: no freeze.json (--allow-unfrozen)")
            return
        raise SystemExit("freeze.json missing; run setup.py first")
    frozen = json.loads(path.read_text(encoding="utf-8"))["files"]
    changed = [rel for rel, digest in frozen.items()
               if sha256(ROOT / rel) != digest]
    if changed:
        msg = "frozen artifacts changed: " + ", ".join(changed)
        if allow:
            print("warning: " + msg)
        else:
            raise SystemExit(msg + "\nuse --allow-unfrozen only for debugging")


def task_meta(task_id: str) -> dict:
    return json.loads((ROOT / "tasks" / task_id / "meta.json").read_text())


def memory_block(arm: str, task_id: str) -> str:
    if arm == "A":
        return "(none)"
    if arm == "B":
        records = []
        for line in (ROOT / "memory" / "records.jsonl").read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line)["text"])
        return "\n".join("- " + text for text in records)
    if arm == "C":
        return (ROOT / "prompts" / "briefs" / f"{task_id}.txt").read_text(
            encoding="utf-8").strip()
    if arm == "D":
        return (ROOT / "prompts" / "irrelevant" / f"{task_id}.txt").read_text(
            encoding="utf-8").strip()
    raise ValueError(f"unknown arm: {arm}")


def build_prompt(task_id: str, arm: str) -> tuple:
    meta = task_meta(task_id)
    system_file = ("system_natural.md" if meta.get("system") == "natural"
                   else "system.md")
    system = (ROOT / "prompts" / system_file).read_text(encoding="utf-8")
    task = (ROOT / "tasks" / task_id / "task.md").read_text(encoding="utf-8")
    user = f"MEMORY:\n{memory_block(arm, task_id)}\n\nTASK:\n{task}"
    return system, user


def call_api(system: str, user: str, *, model: str, max_tokens: int,
             base_url: str, timeout: int = 180,
             retries: int = 5) -> dict:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY missing")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    last = None
    for attempt in range(1, retries + 1):
        try:
            started = time.time()
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            body = json.loads(raw.decode("utf-8"))
            return {"body": body, "latency_ms": int((time.time() - started) * 1000),
                    "attempts": attempt}
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in RETRYABLE or attempt == retries:
                break
        except (urllib.error.URLError, http.client.IncompleteRead,
                ConnectionResetError, TimeoutError,
                json.JSONDecodeError) as exc:
            last = exc
            if attempt == retries:
                break
        wait = min(2 ** attempt, 30)
        print(f"  retry {attempt}/{retries} in {wait}s: {type(last).__name__}")
        time.sleep(wait)
    raise RuntimeError(f"API failed after retries: {last}")


def extract_code(text: str) -> str:
    match = CODE_RE.search(text)
    return match.group(1).strip() + "\n" if match else ""


def run_check(tmp: Path) -> tuple:
    result = subprocess.run([sys.executable, "check.py"], cwd=tmp,
                            capture_output=True, text=True, timeout=60)
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output[-600:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="~/.config/claimledger/deepseek.env")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--tasks", default="")
    parser.add_argument("--arms", default="A,B,C,D")
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--max-calls", type=int, default=100)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--allow-unfrozen", action="store_true")
    args = parser.parse_args()

    load_env(Path(args.env_file))
    model = args.model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    verify_freeze(args.allow_unfrozen)

    task_ids = ([item.strip() for item in args.tasks.split(",") if item.strip()]
                or [path.name for path in sorted((ROOT / "tasks").iterdir())
                    if path.is_dir()])
    arms = [item.strip().upper() for item in args.arms.split(",") if item.strip()]
    results_path = ROOT / "results" / "results.jsonl"
    if args.fresh and (ROOT / "results").exists():
        shutil.rmtree(ROOT / "results")
    (ROOT / "results").mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        for task_id in task_ids:
            for arm in arms:
                system, user = build_prompt(task_id, arm)
                print(f"{task_id} {arm}: system={len(system.split())}w "
                      f"user={len(user.split())}w")
        return 0

    done = set()
    if args.resume and results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("pass"):
                    done.add((row["task"], row["arm"], row["run"]))
    jobs = [(task_id, arm, run)
            for task_id in task_ids
            for arm in arms
            for run in range(1, args.runs + 1)
            if (task_id, arm, run) not in done]
    if args.shuffle:
        random.Random(args.seed).shuffle(jobs)
    calls = 0

    for task_id, arm, run in jobs:
        meta = task_meta(task_id)
        system, user = build_prompt(task_id, arm)
        out_dir = ROOT / "results" / task_id / arm / f"run{run}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "prompt.txt").write_text(
            f"SYSTEM:\n{system}\n\nUSER:\n{user}\n", encoding="utf-8")
        record = {"task": task_id, "arm": arm, "run": run, "model": model,
                  "prompt_tokens": None, "completion_tokens": None,
                  "latency_ms": None, "pass": False, "error": None,
                  "attempts": None, "finish_reason": None,
                  "length_retries": 0}
        if calls >= args.max_calls:
            record["error"] = "max_calls reached"
            _append(results_path, record)
            break
        try:
            budget = args.max_tokens
            content = ""
            for length_try in range(2):
                response = call_api(system, user, model=model,
                                    max_tokens=budget,
                                    base_url=args.base_url,
                                    retries=args.retries)
                calls += 1
                body = response["body"]
                choice = body["choices"][0]
                content = choice["message"]["content"]
                record["latency_ms"] = response["latency_ms"]
                record["attempts"] = response.get("attempts")
                record["finish_reason"] = choice.get("finish_reason")
                usage = body.get("usage") or {}
                record["prompt_tokens"] = usage.get("prompt_tokens")
                record["completion_tokens"] = usage.get("completion_tokens")
                (out_dir / f"attempt{length_try + 1}.txt").write_text(
                    content, encoding="utf-8")
                if record["finish_reason"] != "length" or length_try == 1:
                    break
                record["length_retries"] += 1
                budget = min(budget * 2, 16000)
            (out_dir / "response.txt").write_text(content, encoding="utf-8")
            if record["finish_reason"] == "length":
                record["error"] = "truncated after length retry"
            code = extract_code(content)
            with tempfile.TemporaryDirectory(prefix="e2e_") as tmp_name:
                tmp = Path(tmp_name)
                shutil.copyfile(ROOT / "tasks" / task_id / "check.py",
                                tmp / "check.py")
                if meta["target"]:
                    shutil.copyfile(ROOT / "tasks" / task_id / "starter.py",
                                    tmp / meta["target"])
                    if not code:
                        record["error"] = (
                            f"no code block (finish={record['finish_reason']})")
                    else:
                        (tmp / meta["target"]).write_text(code, encoding="utf-8")
                else:
                    (tmp / "response.txt").write_text(content, encoding="utf-8")
                if not record["error"]:
                    passed, output = run_check(tmp)
                    record["pass"] = passed
                    record["check_output"] = output
        except Exception as exc:  # noqa: BLE001 - one failure must not stop the run
            record["error"] = f"{type(exc).__name__}: {exc}"
        _append(results_path, record)
        (out_dir / "meta.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"{task_id:22} {arm} run{run} "
              f"{'PASS' if record['pass'] else 'fail'} "
              f"{record['error'] or ''}", flush=True)
        time.sleep(args.sleep)
    return 0


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())