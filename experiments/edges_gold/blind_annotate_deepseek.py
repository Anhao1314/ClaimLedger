"""Phase 1 dual-model cross-validation: DeepSeek blind annotation of 120 pairs.

The model sees only the pair texts and a self-contained copy of the annotation
specification (mirroring docs/annotation-guide-full.md). It receives no pair
metadata, no other annotator's labels, and no hint about how the corpus was
constructed.

Usage:
    python experiments/edges_gold/blind_annotate_deepseek.py \
        --env-file ~/.config/claimledger/deepseek.env

Writes:
    experiments/edges_gold/annotation-deepseek.jsonl   (append + resume)
"""
from __future__ import annotations

import argparse
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
CANDIDATES = ROOT / "candidates.jsonl"
OUTPUT = ROOT / "annotation-deepseek.jsonl"

SPEC = """You are annotating the relationship between pairs of records from a project's decision log. Each record is a standalone statement. Classify each pair into exactly one of five types.

## The five types

### supports
One record provides evidence, refinement, elaboration, or repetition for the other. If you follow one, the other is reinforced or at least not contradicted.
- One is a specific instance or application of the other
- One explains why the other exists
- Both state the same constraint using different wording
- One adds operational detail to a high-level rule without changing it
Do NOT mark supports when the records are about different systems or concerns (that is unrelated), when one replaces the other (supersedes), or when following one makes the other impossible (contradicts).

### contradicts
Following both records is impossible. One record forbids what the other requires, or they specify incompatible values for the same thing.
- One says "must do X" and the other says "must not do X"
- They specify different numeric limits for the same thing
- One applies to all services and the other bans it for a specific service, making compliance impossible
Do NOT mark contradicts when the records are about different scopes and can both be followed in their own scope.

### supersedes
One record replaces the other due to a decision change, version update, or time passage. The superseded record is no longer intended to be followed.
- One is explicitly a newer version of the other
- One reverses a previous decision
- One is marked as deprecated/replaced in the text
Requires direction. Convention: A is the first record, B is the second; direction "A→B" means A supersedes B.
Do NOT mark supersedes when the records merely conflict with neither clearly newer — that is contradicts.

### unrelated
The two records talk about different aspects, systems, or concerns. Following one has no bearing on the other.
- Different subsystems, tools, or teams
- Different abstraction levels with no shared constraint
Do NOT mark unrelated when they share a common resource or constraint even if the wording differs.

### abstain
The relationship cannot be determined from the available context. Use sparingly.

## Confidence
0.9-1.0 certain; 0.7-0.9 confident; 0.5-0.7 uncertain; below 0.5 should be abstain.

## Common pitfalls
1. Same topic but different services can both be followed — not contradicts.
2. contradicts requires impossibility; supersedes requires an explicit replacement semantic.
3. Do not mark supports for records that merely coexist.
4. When a record says "retained for N days" or similar, treat the numeric value as part of the record: different values for the same metric are contradicts."""

INSTRUCTION = """Classify the relationship between the following two records.

RECORD A (src):
{a}

RECORD B (dst):
{b}

Respond with ONLY a JSON object, no prose, no markdown fences:
{{"edge_type": "supports|contradicts|supersedes|unrelated|abstain", "confidence": <0.0-1.0>, "direction": null or "A→B", "reason": "<one sentence, <=120 chars>"}}"""

JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
RETRYABLE = {429, 500, 502, 503, 504, 529}


def call_api(system: str, user: str, *, model: str, base_url: str,
             timeout: int = 120, retries: int = 5) -> str:
    key = os.environ["DEEPSEEK_API_KEY"]
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": 2000,
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
            return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in RETRYABLE or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt == retries:
                raise
        wait = min(2 ** attempt, 30)
        print(f"  retry {attempt}/{retries} in {wait}s", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"unreachable: {last}")


def parse_label(text: str) -> dict:
    match = JSON_RE.search(text)
    if not match:
        raise ValueError(f"no JSON in response: {text[:120]}")
    data = json.loads(match.group(0))
    if data.get("edge_type") not in ("supports", "contradicts", "supersedes",
                                     "unrelated", "abstain"):
        raise ValueError(f"bad edge_type: {data.get('edge_type')}")
    conf = float(data.get("confidence", 0.0))
    data["confidence"] = max(0.0, min(1.0, conf))
    direction = data.get("direction")
    if direction not in (None, "A→B"):
        direction = None
    data["direction"] = direction
    return data


def annotate_one(pair: dict, *, model: str, base_url: str) -> dict:
    user = INSTRUCTION.format(a=pair["src_text"], b=pair["dst_text"])
    raw = call_api(SPEC, user, model=model, base_url=base_url)
    label = parse_label(raw)
    return {
        "pair_id": pair["pair_id"],
        "src_text": pair["src_text"],
        "dst_text": pair["dst_text"],
        "edge_type": label["edge_type"],
        "confidence": label["confidence"],
        "direction": label["direction"],
        "reason": label.get("reason", ""),
        "annotator": f"deepseek:{model}",
        "guide": "docs/annotation-guide-full.md (inlined in prompt)",
        "raw_response": raw,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="~/.config/claimledger/deepseek.env")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    env_path = Path(os.path.expanduser(args.env_file))
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                k = k.replace("export", "").strip()
                os.environ.setdefault(k, v.strip().strip("'\""))
    if "DEEPSEEK_API_KEY" not in os.environ:
        raise SystemExit("DEEPSEEK_API_KEY missing")
    model = args.model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    pairs = [json.loads(line) for line in CANDIDATES.read_text().splitlines()
             if line.strip()]
    done = set()
    if OUTPUT.exists():
        for line in OUTPUT.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["pair_id"])
    todo = [p for p in pairs if p["pair_id"] not in done]
    print(f"pairs: {len(pairs)} total, {len(done)} done, {len(todo)} to run")

    if todo:
        with open(OUTPUT, "a", encoding="utf-8") as handle, \
                ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(annotate_one, p, model=model,
                                   base_url=args.base_url): p for p in todo}
            failures = 0
            for future in as_completed(futures):
                pair = futures[future]
                try:
                    row = future.result()
                    handle.write(json.dumps(row, ensure_ascii=False,
                                            sort_keys=True) + "\n")
                    handle.flush()
                except Exception as exc:  # noqa: BLE001 — per-pair isolation
                    failures += 1
                    print(f"FAIL {pair['pair_id']}: {type(exc).__name__}: {exc}")
            if failures:
                print(f"{failures} pairs failed; rerun to resume")

    rows = [json.loads(line) for line in OUTPUT.read_text().splitlines()
            if line.strip()]
    print(f"output: {len(rows)} rows")
    return 0 if len(rows) == len(pairs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
