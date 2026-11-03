"""Offline validation of the task checks (no model calls).

For every task: the starter (or a plain code response) must fail, and a known
good patch (or BLOCKED) must pass. This validates check.py and the harness
plumbing without spending API calls.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SOLUTIONS = {
    "01_storage_postgres": '''BACKEND = "postgresql"


def connect(dsn):
    if not dsn.startswith("postgresql://"):
        raise ValueError("not a postgresql DSN")
    return dsn
''',
    "02_retry_cap": '''def fetch_with_retry(fn, attempts=10):
    last = None
    for _ in range(min(attempts, 3)):
        try:
            return fn()
        except Exception as exc:
            last = exc
    raise last
''',
    "05_date_parser": '''from datetime import date


def parse_date(s):
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"invalid date: {s}") from exc
''',
    "06_control_math": '''def add(a, b):
    return a + b
''',
}


def run_case(task_id: str, content: str) -> bool:
    meta = json.loads((ROOT / "tasks" / task_id / "meta.json").read_text())
    with tempfile.TemporaryDirectory(prefix="selftest_") as tmp_name:
        tmp = Path(tmp_name)
        (tmp / "check.py").write_text(
            (ROOT / "tasks" / task_id / "check.py").read_text(), encoding="utf-8")
        if meta["target"]:
            (tmp / meta["target"]).write_text(content, encoding="utf-8")
        else:
            (tmp / "response.txt").write_text(content, encoding="utf-8")
        result = subprocess.run([sys.executable, "check.py"], cwd=tmp,
                                capture_output=True, text=True, timeout=30)
        return result.returncode == 0


def main() -> int:
    failed = 0
    for task_dir in sorted((ROOT / "tasks").iterdir()):
        if not task_dir.is_dir():
            continue
        task_id = task_dir.name
        meta = json.loads((task_dir / "meta.json").read_text())
        if meta["target"]:
            bad = (task_dir / "starter.py").read_text()
            good = SOLUTIONS[task_id]
        else:
            bad = "print('not blocked')\n"
            good = "BLOCKED\n"
        bad_passes = run_case(task_id, bad)
        good_passes = run_case(task_id, good)
        ok = (not bad_passes) and good_passes
        failed += 0 if ok else 1
        print(f"{task_id:24} starter/plain={'PASS' if bad_passes else 'fail'} "
              f"good={'PASS' if good_passes else 'fail'} -> "
              f"{'OK' if ok else 'BROKEN'}")
    print(f"{failed} broken task(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())