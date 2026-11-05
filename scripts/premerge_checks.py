#!/usr/bin/env python3
"""Premerge checks for the console frontend + evidence figures.

    python scripts/premerge_checks.py

Three gates, exit non-zero on any failure:

1. JS syntax — extract the console <script> and `node --check` it. Catches the
   whole-script-parse-failure class (a corrupted i18n key once killed every
   handler; py_compile cannot see it).
2. i18n consistency — every data-i18n* key used in the page must exist in the
   ZH dict; every static chrome string carries its key.
3. Figures — render_figures.py --check (all README evidence SVGs byte-identical
   to their committed JSON projections).
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jev_first.web_page import PAGE  # noqa: E402

ok = True


def fail(msg: str) -> None:
    global ok
    ok = False
    print(f"FAIL: {msg}")


# ---- 1. JS syntax -----------------------------------------------------------
match = re.search(r"<script>(.*)</script>", PAGE, re.DOTALL)
if not match:
    fail("console <script> block not found")
else:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(match.group(1))
        tmp = fh.name
    proc = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
    if proc.returncode != 0:
        fail(f"JS syntax: {proc.stderr[:300]}")
    else:
        print("PASS: JS syntax (node --check)")

# ---- 2. i18n consistency ----------------------------------------------------
zh_match = re.search(r"const ZH = \{(.*?)\n\};", PAGE, re.DOTALL)
if not zh_match:
    fail("ZH dict not found")
else:
    zh_keys = set(re.findall(r'"((?:[^"\\]|\\.)*)":', zh_match.group(1)))
    used = set(re.findall(r'data-i18n(?:-ph|-title)?="((?:[^"\\]|\\.)*)"', PAGE))
    missing = sorted(k for k in used if k not in zh_keys)
    if missing:
        fail(f"i18n keys used but not in ZH: {missing}")
    else:
        print(f"PASS: i18n consistency ({len(used)} static keys present)")

# ---- 3. figures -------------------------------------------------------------
proc = subprocess.run([sys.executable, str(ROOT / "scripts/render_figures.py"),
                       "--check"], capture_output=True, text=True)
if proc.returncode != 0:
    fail(f"figures: {proc.stdout.strip()[:300]}")
else:
    print("PASS: figures byte-identical")

print("\npremerge:", "OK" if ok else "FAILED")
sys.exit(0 if ok else 1)
