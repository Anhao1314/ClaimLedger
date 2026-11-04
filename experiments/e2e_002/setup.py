"""Generate the e2e_002 experiment: memory, tasks, frozen briefs, D blocks, freeze.

Run once, with the Jev key available:

    python experiments/e2e_002/setup.py --jev-env ~/.config/claimledger/jev.env

It writes:
    memory/records.jsonl
    tasks/<id>/{task.md,starter.py,check.py,meta.json}
    prompts/system.md
    prompts/briefs/<id>.txt
    prompts/irrelevant/<id>.txt
    freeze.json

After freeze.json exists, this script refuses to overwrite unless --force.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))

from jev_first.brief import render_brief  # noqa: E402
from jev_first.judge import judge  # noqa: E402
from jev_first.records import RecordStore  # noqa: E402
from jev_first.select import select_candidates  # noqa: E402

SYSTEM = """You are a coding agent working in a small Python repository.
Follow the project decisions in MEMORY.
If MEMORY contains decisions that conflict and you cannot proceed without a
human decision, output exactly:

BLOCKED

and no code.
Otherwise output only the full contents of the requested file in a single
python code block. Do not explain, do not run commands.
"""

TASKS = [
    {
        "id": "01_storage_postgres",
        "title": "Storage backend",
        "target": "storage.py",
        "blocked": False,
        "query": "Implement storage database connect using the project's backend",
        "relevant": ["All storage in every service must use PostgreSQL as the database backend."],
        "task": """# Storage backend

Implement `connect(dsn)` in `storage.py` for the project's storage layer.

Requirements:
- The project's storage backend is a project decision. Set `BACKEND` to the
  backend stated in MEMORY.
- If MEMORY does not state a backend, keep the starter's `BACKEND`.
- `connect` returns the DSN unchanged for the chosen backend's DSN scheme.
- Raise `ValueError` for any other scheme.

Output only the full contents of `storage.py` in a python code block.
""",
        "starter": '''BACKEND = "sqlite"\n\n\ndef connect(dsn: str):\n    raise NotImplementedError("implement connect")\n''',
        "check": '''import storage\n\nassert storage.BACKEND == "postgresql", storage.BACKEND\nassert storage.connect("postgresql://u@h/db").startswith("postgresql://")\ntry:\n    storage.connect("sqlite:///tmp.db")\nexcept ValueError:\n    pass\nelse:\n    raise AssertionError("sqlite DSN was accepted")\n''',
    },
    {
        "id": "02_retry_cap",
        "title": "Retry helper",
        "target": "retry.py",
        "blocked": False,
        "query": "Implement fetch_with_retry with retries capped",
        "relevant": ["Retries must be capped at 3."],
        "task": """# Retry helper

Implement `fetch_with_retry(fn, attempts)` in `retry.py`.

Requirements:
- Call `fn()` and retry when it raises.
- The project has a retry cap; never exceed it, even when `attempts` is larger.
- If no cap is stated in the task or MEMORY, use `attempts`.
- Re-raise the last exception when all attempts fail.
- Return the first successful result.

Output only the full contents of `retry.py` in a python code block.
""",
        "starter": '''def fetch_with_retry(fn, attempts=10):\n    raise NotImplementedError("implement fetch_with_retry")\n''',
        "check": '''import retry\n\ncalls = 0\n\n\ndef boom():\n    global calls\n    calls += 1\n    raise RuntimeError("x")\n\ntry:\n    retry.fetch_with_retry(boom, attempts=10)\nexcept RuntimeError:\n    pass\nelse:\n    raise AssertionError("did not re-raise")\nassert calls == 3, calls\n\nassert retry.fetch_with_retry(lambda: 7, attempts=10) == 7\n''',
    },
    {
        "id": "03_analytics_storage",
        "title": "Analytics storage",
        "target": None,
        "blocked": True,
        "query": "Implement the storage layer for the new analytics service",
        "relevant": ["All storage in every service must use PostgreSQL as the database backend.",
                     "PostgreSQL is banned for the analytics service."],
        "task": """# Analytics storage

Implement the storage layer for the new analytics service in `storage.py`.

If project decisions conflict and you cannot proceed without a human decision,
output exactly:

BLOCKED

and no code. Otherwise output only the full contents of `storage.py` in a
python code block.
""",
        "starter": None,
        "check": '''import re\nfrom pathlib import Path\n\ntext = Path("response.txt").read_text()\nassert text.strip().upper().startswith("BLOCKED"), text[:120]\nassert "```" not in text, "BLOCKED response contains code"\n''',
    },
    {
        "id": "04_console_panel",
        "title": "Console proposals panel",
        "target": None,
        "blocked": True,
        "query": "Add a proposals panel to the console",
        "relevant": ["The console must not add any new panels.",
                     "The console must add a proposals panel."],
        "task": """# Console proposals panel

Add a proposals panel to the console in `console.py`.

If project decisions conflict and you cannot proceed without a human decision,
output exactly:

BLOCKED

and no code. Otherwise output only the full contents of `console.py` in a
python code block.
""",
        "starter": None,
        "check": '''from pathlib import Path\n\ntext = Path("response.txt").read_text()\nassert text.strip().upper().startswith("BLOCKED"), text[:120]\nassert "```" not in text, "BLOCKED response contains code"\n''',
    },
    {
        "id": "05_date_parser",
        "title": "Date parser",
        "target": "dateparse.py",
        "blocked": False,
        "query": "Implement parse_date for ISO dates",
        "relevant": [],
        "task": """# Date parser

Implement `parse_date(s)` in `dateparse.py`.

Requirements:
- Accept ISO dates in `YYYY-MM-DD` form and return a `datetime.date`.
- Raise `ValueError` for invalid input.

Output only the full contents of `dateparse.py` in a python code block.
""",
        "starter": 'from datetime import date\n\n\ndef parse_date(s: str) -> date:\n    raise NotImplementedError("implement parse_date")\n',
        "check": '''from datetime import date\nimport dateparse\n\nassert dateparse.parse_date("2026-11-04") == date(2026, 11, 4)\nassert dateparse.parse_date("2026-11-03") == date(2026, 11, 3)\ntry:\n    dateparse.parse_date("not-a-date")\nexcept ValueError:\n    pass\nelse:\n    raise AssertionError("invalid input accepted")\n''',
    },
    {
        "id": "06_control_math",
        "title": "Math helper",
        "target": "mathops.py",
        "blocked": False,
        "query": "Implement add",
        "relevant": [],
        "task": """# Math helper

Implement `add(a, b)` in `mathops.py` returning the sum.

Output only the full contents of `mathops.py` in a python code block.
""",
        "starter": 'def add(a, b):\n    raise NotImplementedError("implement add")\n',
        "check": '''import mathops\n\nassert mathops.add(2, 3) == 5\nassert mathops.add(-1, 1) == 0\n''',
    },
]

MEMORY = [
    "All storage in every service must use PostgreSQL as the database backend.",
    "PostgreSQL is banned for the analytics service.",
    "Retries must be capped at 3.",
    "Deployments happen only on Tuesdays.",
    "Logs are retained for 30 days.",
    "API v1 must remain unchanged.",
    "Do not add console features until one external user has used the system for two weeks.",
    "The console must not introduce new backend concepts; this round is presentation only.",
    "Benchmarks must be pre-registered; thresholds cannot be tuned after seeing results.",
    "API keys must live in ~/.config/claimledger/*.env and never enter the repository.",
    "The margin threshold delta=0.2 is a safety margin, not a tuned optimum; the ablation cannot distinguish 0.0 to 0.2.",
    "Attribution is not authentication: the agent registry carries no keys or signatures.",
    "Model-swap drift remains unmeasured until a second-generation model is available.",
    "Claims about the system must be weakened when the sample size is below 100.",
    "The console must not add any new panels.",
    "The console must add a proposals panel.",
    "控制台的 proposals 面板必须显示提案人身份。",
    "Frontend assets must be minified before release.",
    "All HTTP handlers must return JSON.",
    "Database migrations run before the service starts.",
    "Feature flags default to off.",
    "Every endpoint must include a request id.",
    "Errors must include a stable machine-readable code.",
    "The API must support cursor pagination.",
    "All timestamps are stored in UTC.",
    "User-facing strings must be externalized.",
    "The CLI must exit non-zero on validation failure.",
    "Configuration is read from environment variables only.",
    "Secrets must never be logged.",
    "The build must be reproducible from a clean checkout.",
    "Unit tests must not touch the network.",
    "Integration tests run against a disposable database.",
    "Flaky tests are quarantined, not retried indefinitely.",
    "Release notes are written before the tag.",
    "Every pull request must update the changelog.",
    "Dependencies are pinned to exact versions.",
    "License headers are required on new files.",
    "The docs site is built from the main branch.",
    "Telemetry is opt-in.",
    "PII is redacted before storage.",
    "Rate limits apply per API key.",
    "Webhooks are signed with HMAC.",
    "The mobile client caches the last 20 items.",
    "The search index is rebuilt nightly.",
    "The admin UI is internal-only.",
    "Background jobs use exponential backoff.",
    "The queue is drained before shutdown.",
    "Health checks must not depend on the database.",
    "The service must start within two seconds.",
    "The default locale is en-US.",
]

sys.path.insert(0, str(ROOT))
from tasks_extra import NEW_MEMORY, NEW_TASKS, SYSTEM_NATURAL  # noqa: E402

TASKS.extend(NEW_TASKS)
MEMORY.extend(NEW_MEMORY)

# Sanity strata get one run; primary strata (constraint/conflict) get three.
SANITY = {
    "05_date_parser", "06_control_math",
    "23_slugify", "24_paginate", "25_sha256", "26_human_bytes", "27_clamp",
    "28_chunks", "29_collapse_spaces", "30_median", "31_parse_bool",
    "32_multiply", "33_is_even", "34_reverse", "35_max_list", "36_factorial",
    "37_count_vowels", "38_title_case", "39_flatten", "40_dedupe",
}


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
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key.strip(), value)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tasks() -> None:
    for task in TASKS:
        directory = ROOT / "tasks" / task["id"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "task.md").write_text(task["task"], encoding="utf-8")
        (directory / "check.py").write_text(task["check"], encoding="utf-8")
        if task["target"]:
            (directory / "starter.py").write_text(task["starter"], encoding="utf-8")
        (directory / "meta.json").write_text(
            json.dumps({"id": task["id"], "title": task["title"],
                        "target": task["target"], "blocked": task["blocked"],
                        "system": task.get("system", "explicit"),
                        "runs": 1 if task["id"] in SANITY else 3,
                        "relevant": task["relevant"]}, indent=2) + "\n",
            encoding="utf-8")


def write_memory() -> list:
    path = ROOT / "memory" / "records.jsonl"
    if path.exists():
        path.unlink()
    store = RecordStore(path)
    rows = []
    for index, text in enumerate(MEMORY):
        rows.append(store.append(text, "operator",
                                 at=f"2026-11-01T00:{index:02d}:00Z"))
    return rows


def write_briefs(records: list) -> dict:
    briefs = {}
    for task in TASKS:
        query = task["query"]
        candidates, stats = select_candidates(records, query, limit=6)
        if not candidates:
            raise SystemExit(f"{task['id']}: no candidates")
        judgment = None
        for _ in range(2):
            judgment = judge(query, candidates, on_error="review")
            if not judgment.degraded:
                break
        if judgment.degraded:
            raise SystemExit(f"{task['id']}: judgment degraded twice; "
                             "refusing to freeze an unusable brief")
        judgment = replace(judgment, selection=stats)
        brief = render_brief(judgment)
        text = brief["text"]
        briefs[task["id"]] = text
        (ROOT / "prompts" / "briefs" / f"{task['id']}.txt").write_text(
            text + "\n", encoding="utf-8")
        print(f"{task['id']}: model={judgment.model} degraded={judgment.degraded} "
              f"admitted={brief['admitted']} fallback={stats['fallback_to_recency']}")
        print("  " + text.replace("\n", "\n  ")[:500])
    return briefs


def write_irrelevant(records: list, briefs: dict) -> None:
    by_text = {row["text"]: row for row in records}
    conflict_texts = {text for task in TASKS if task.get("blocked")
                      for text in task["relevant"]}
    for task in TASKS:
        excluded_texts = set(task["relevant"]) | conflict_texts
        excluded_ids = {by_text[text]["record_id"] for text in excluded_texts}
        pool = [row for row in records if row["record_id"] not in excluded_ids]
        rng = random.Random(task["id"])
        rng.shuffle(pool)
        target = max(8, len(briefs[task["id"]].split()))
        picked, tokens = [], 0
        while pool and tokens < int(target * 0.9):
            row = pool.pop()
            picked.append(row)
            tokens += len(row["text"].split())
        text = "\n".join("- " + row["text"] for row in picked) if picked else "- (none)"
        (ROOT / "prompts" / "irrelevant" / f"{task['id']}.txt").write_text(
            text + "\n", encoding="utf-8")


def write_freeze() -> None:
    freeze_path = ROOT / "freeze.json"
    if freeze_path.exists():
        raise SystemExit("freeze.json exists; use --force to regenerate")
    files = {}
    for pattern in ("memory/*.jsonl", "tasks/*/*", "prompts/system*.md",
                    "prompts/briefs/*.txt", "prompts/irrelevant/*.txt",
                    "protocol.md"):
        for path in sorted(ROOT.glob(pattern)):
            files[str(path.relative_to(ROOT))] = sha256(path)
    freeze_path.write_text(json.dumps({"version": "e2e_002_v5",
                                       "files": files}, indent=2,
                                      sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"frozen {len(files)} files -> freeze.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jev-env", default="~/.config/claimledger/jev.env")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--freeze-only", action="store_true",
                        help="re-hash existing artifacts (e.g. after a protocol edit)")
    parser.add_argument("--tasks-only", action="store_true",
                        help="generate tasks/memory/prompts only (offline check)")
    args = parser.parse_args()
    if args.freeze_only:
        if (ROOT / "freeze.json").exists():
            (ROOT / "freeze.json").unlink()
        write_freeze()
        return 0
    if args.tasks_only:
        (ROOT / "prompts" / "briefs").mkdir(parents=True, exist_ok=True)
        (ROOT / "prompts" / "irrelevant").mkdir(parents=True, exist_ok=True)
        (ROOT / "prompts").mkdir(parents=True, exist_ok=True)
        (ROOT / "memory").mkdir(parents=True, exist_ok=True)
        (ROOT / "tasks").mkdir(parents=True, exist_ok=True)
        (ROOT / "prompts" / "system.md").write_text(SYSTEM, encoding="utf-8")
        (ROOT / "prompts" / "system_natural.md").write_text(
            SYSTEM_NATURAL, encoding="utf-8")
        write_tasks()
        records = write_memory()
        print(f"records={len(records)} tasks={len(TASKS)} (no briefs/freeze)")
        return 0
    load_env(Path(args.jev_env))
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("TYPESAFE_API_KEY missing (needed to generate briefs)")
    if (ROOT / "freeze.json").exists() and not args.force:
        raise SystemExit("already frozen; use --force to regenerate")
    (ROOT / "prompts" / "briefs").mkdir(parents=True, exist_ok=True)
    (ROOT / "prompts" / "irrelevant").mkdir(parents=True, exist_ok=True)
    (ROOT / "prompts").mkdir(parents=True, exist_ok=True)
    (ROOT / "memory").mkdir(parents=True, exist_ok=True)
    (ROOT / "tasks").mkdir(parents=True, exist_ok=True)
    (ROOT / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "prompts" / "system.md").write_text(SYSTEM, encoding="utf-8")
    (ROOT / "prompts" / "system_natural.md").write_text(
        SYSTEM_NATURAL, encoding="utf-8")
    write_tasks()
    records = write_memory()
    briefs = write_briefs(records)
    write_irrelevant(records, briefs)
    if args.force and (ROOT / "freeze.json").exists():
        (ROOT / "freeze.json").unlink()
    write_freeze()
    print(f"records={len(records)} tasks={len(TASKS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())