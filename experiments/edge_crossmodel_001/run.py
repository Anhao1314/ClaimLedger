"""edge_crossmodel_001 runner: deepseek-flash on the frozen edge question.

    python experiments/edge_crossmodel_001/run.py

351 calls (117 pairs x 3 runs, temperature 0). Criteria are rendered verbatim
from contracts/questions.v3.json; state format identical to edges_v1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))

RUNS = 3
LABELS = ("supports", "contradicts", "supersedes", "unrelated")
JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
RETRYABLE = {429, 500, 502, 503, 504, 529}


def verify_manifest() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for name, entry in manifest["files"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            raise SystemExit(f"manifest mismatch: {name} changed after freeze")


def build_prompt() -> tuple:
    spec = json.loads((REPO / "contracts" / "questions.v3.json")
                      .read_text(encoding="utf-8"))
    edge = spec["questions"]["edge"]
    criteria = edge["criteria"]
    system = ("You classify the relation between two memory records of a project "
              "decision log. Answer only with a JSON object containing a "
              "probability for each label; the four probabilities must sum to 1.0.")
    lines = ["Relation criteria:"]
    for label in LABELS:
        lines.append(f"- {label}: {criteria[label]}")
    lines += ["", "Record A (src): {a}", "Record B (dst): {b}", "",
              "Answer only with JSON: "
              '{{"probabilities": {{"supports": 0.0, "contradicts": 0.0, '
              '"supersedes": 0.0, "unrelated": 0.0}}}}']
    return system, "\n".join(lines)


def call_api(system: str, user: str, *, model: str, key: str, base_url: str,
             timeout: float, retries: int) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    last = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            return body["choices"][0]["message"].get("content") or ""
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in RETRYABLE or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt == retries:
                raise
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"unreachable: {last}")


def ask(pair: dict, system: str, user_template: str, *, model: str, key: str,
        base_url: str, timeout: float, retries: int) -> dict:
    user = user_template.format(a=pair["src_text"], b=pair["dst_text"])
    started = time.monotonic()
    try:
        content = call_api(system, user, model=model, key=key,
                           base_url=base_url, timeout=timeout, retries=retries)
    except Exception as exc:  # noqa: BLE001
        return {"parse": False, "label": None, "probs": None,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}"[:120]}
    latency = int((time.monotonic() - started) * 1000)
    try:
        match = JSON_RE.search(content)
        if not match:
            raise ValueError("no JSON")
        probs = json.loads(match.group(0)).get("probabilities") or {}
        values = {l: float(probs.get(l, 0.0)) for l in LABELS}
        if any(v < 0 for v in values.values()) or sum(values.values()) <= 0:
            raise ValueError("bad probabilities")
        total = sum(values.values())
        values = {l: v / total for l, v in values.items()}
        return {"parse": True, "label": max(values, key=values.get),
                "probs": {l: round(v, 4) for l, v in values.items()},
                "latency_ms": latency}
    except (ValueError, json.JSONDecodeError, AttributeError) as exc:
        return {"parse": False, "label": None, "probs": None,
                "latency_ms": latency,
                "error": f"parse: {exc}: {content[:80]}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="~/.config/claimledger/deepseek.env")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
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
    key = os.environ["DEEPSEEK_API_KEY"]
    model = args.model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    verify_manifest()
    pairs = [json.loads(line) for line in
             (ROOT / "pairs.jsonl").read_text().splitlines() if line.strip()]
    pairs = [p for p in pairs if p["in_gold"]]
    system, user_template = build_prompt()

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
    print(f"pairs: {len(pairs)}, slots: {len(slots)} to run ({len(done)} done)")

    failures = 0
    with open(out, "a", encoding="utf-8") as handle, \
            ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for pair, run in slots:
            futures[pool.submit(ask, pair, system, user_template, model=model,
                                key=key, base_url=args.base_url,
                                timeout=args.timeout,
                                retries=args.retries)] = (pair, run)
        for future in as_completed(futures):
            pair, run = futures[future]
            result = future.result()
            if not result["parse"]:
                failures += 1
                print(f"FAIL {pair['pair_id']} run {run}: {result.get('error')}")
                continue
            handle.write(json.dumps({
                "pair_id": pair["pair_id"], "run": run, "gold": pair["gold"],
                **result}, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()

    rows = [json.loads(line) for line in out.read_text().splitlines()
            if line.strip()]
    print(f"output: {len(rows)} rows ({failures} failures)")
    return 0 if len(rows) == len(pairs) * args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
