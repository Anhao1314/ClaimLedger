#!/usr/bin/env python3
"""LongMemEval-S stage-0 audit: verify data, freeze splits, project cost.

No model calls are made here. The script verifies the downloaded file against
``data/manifest.json``, reports dataset scale, builds the seed-42 stratified
dev/report samples, and prices the planned extraction/answer/judge calls from
explicit assumptions. Token counts for haystacks are ``chars / 3`` estimates,
not tokenizer output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "data" / "longmemeval_s_cleaned.json"
DEFAULT_MANIFEST = HERE / "data" / "manifest.json"
DEFAULT_OUT = HERE / "data-stats.json"

SEED = 42
CHARS_PER_TOKEN = 3
DEV_KU, DEV_ABS = 20, 10
REPORT_KU, REPORT_ABS = 40, 20

KIMI_PAID = {
    "input_usd_per_mtok": 0.95,
    "output_usd_per_mtok": 4.00,
    "cached_input_usd_per_mtok": 0.16,
}
DEEPSEEK_PEAK = {
    "input_usd_per_mtok": 0.30,
    "output_usd_per_mtok": 1.20,
    "note": "deepseek-flash peak price; off-peak is half. Judge is a separate vendor from the answer model.",
}
USD_TO_CNY = 7.1


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(records):
    if not isinstance(records, list) or len(records) != 500:
        raise ValueError("expected the 500-question LongMemEval-S file")
    required = {
        "question_id", "question_type", "question", "answer", "answer_session_ids",
        "haystack_session_ids", "haystack_dates", "haystack_sessions",
    }
    seen = set()
    for record in records:
        missing = required - set(record)
        if missing:
            raise ValueError("missing fields on %r: %s" % (record.get("question_id"), sorted(missing)))
        qid = record["question_id"]
        if qid in seen:
            raise ValueError("duplicate question_id: %s" % qid)
        seen.add(qid)
        sessions = record["haystack_sessions"]
        if not (len(sessions) == len(record["haystack_session_ids"]) == len(record["haystack_dates"])):
            raise ValueError("parallel haystack arrays differ on %s" % qid)
        if not sessions:
            raise ValueError("empty haystack on %s" % qid)
        for session in sessions:
            if not isinstance(session, list) or not session:
                raise ValueError("empty session on %s" % qid)
            for turn in session:
                if not isinstance(turn, dict) or turn.get("role") not in ("user", "assistant"):
                    raise ValueError("bad turn role on %s" % qid)
                if not isinstance(turn.get("content"), str):
                    raise ValueError("bad turn content on %s" % qid)


def distribution(values):
    values = sorted(values)
    if not values:
        return {}
    n = len(values)

    def nearest_rank(p):
        return values[max(0, min(n - 1, math.ceil(p * n) - 1))]

    return {
        "min": values[0],
        "p25": nearest_rank(0.25),
        "median": nearest_rank(0.50),
        "p75": nearest_rank(0.75),
        "p90": nearest_rank(0.90),
        "p95": nearest_rank(0.95),
        "max": values[-1],
        "mean": round(sum(values) / n, 2),
        "total": sum(values),
    }


def session_char_counts(record):
    return [sum(len(turn["content"]) for turn in session) for session in record["haystack_sessions"]]


def pool_summary(records, ids):
    by_id = {record["question_id"]: record for record in records}
    chars = [value for qid in ids for value in session_char_counts(by_id[qid])]
    turns = [sum(len(session) for session in by_id[qid]["haystack_sessions"]) for qid in ids]
    return {
        "questions": len(ids),
        "by_type": dict(sorted(Counter(by_id[qid]["question_type"] for qid in ids).items())),
        "knowledge_update_non_abs": sum(
            1 for qid in ids
            if by_id[qid]["question_type"] == "knowledge-update" and not qid.endswith("_abs")),
        "abstention": sum(1 for qid in ids if qid.endswith("_abs")),
        "sessions": len(chars),
        "turns": sum(turns),
        "characters": sum(chars),
        "estimated_tokens_chars_div_3": sum(math.ceil(value / CHARS_PER_TOKEN) for value in chars),
        "session_characters": chars,
        "ids": sorted(ids),
        "ids_sha256": hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest(),
    }


def build_splits(records, seed=SEED):
    abs_pool = sorted(r["question_id"] for r in records if r["question_id"].endswith("_abs"))
    ku_pool = sorted(r["question_id"] for r in records
                     if r["question_type"] == "knowledge-update"
                     and not r["question_id"].endswith("_abs"))
    if len(abs_pool) < DEV_ABS + REPORT_ABS:
        raise ValueError("not enough abstention questions: %d" % len(abs_pool))
    if len(ku_pool) < DEV_KU + REPORT_KU:
        raise ValueError("not enough non-abstention KU questions: %d" % len(ku_pool))
    rng = random.Random(seed)
    dev_ku = sorted(rng.sample(ku_pool, DEV_KU))
    dev_abs = sorted(rng.sample(abs_pool, DEV_ABS))
    remaining_ku = [qid for qid in ku_pool if qid not in set(dev_ku)]
    remaining_abs = [qid for qid in abs_pool if qid not in set(dev_abs)]
    report_ku = sorted(rng.sample(remaining_ku, REPORT_KU))
    report_abs = sorted(rng.sample(remaining_abs, REPORT_ABS))
    dev = dev_ku + dev_abs
    report = report_ku + report_abs
    if set(dev) & set(report):
        raise ValueError("dev/report overlap")
    return {
        "seed": seed,
        "algorithm": (
            "sorted pools; random.Random(42).sample in the order dev KU, dev ABS, "
            "report KU, report ABS; sorted output; report drawn from the remainder"
        ),
        "pools": {
            "knowledge_update_non_abs": len(ku_pool),
            "abstention": len(abs_pool),
            "knowledge_update_total_including_abs": len(ku_pool) + sum(
                1 for r in records if r["question_type"] == "knowledge-update"
                and r["question_id"].endswith("_abs")),
            "unused_knowledge_update_non_abs": len(ku_pool) - DEV_KU - REPORT_KU,
            "unused_abstention": len(abs_pool) - DEV_ABS - REPORT_ABS,
        },
        "dev": pool_summary(records, dev),
        "report": pool_summary(records, report),
    }


def price(tokens, usd_per_mtok):
    return tokens / 1_000_000 * usd_per_mtok


def block(input_tokens, output_tokens, prices):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usd": round(price(input_tokens, prices["input_usd_per_mtok"])
                     + price(output_tokens, prices["output_usd_per_mtok"]), 6),
    }


def with_micro(block_value):
    result = dict(block_value)
    result["micro_usd"] = round(result["usd"] * 1_000_000)
    result["cny_at_7_1"] = round(result["usd"] * USD_TO_CNY, 2)
    return result


def project_cost(splits):
    dev = splits["dev"]
    report = splits["report"]
    dev_sessions = dev["sessions"]
    report_sessions = report["sessions"]
    dev_input = sum(1000 + math.ceil(chars / CHARS_PER_TOKEN) for chars in dev["session_characters"])
    report_input = sum(1000 + math.ceil(chars / CHARS_PER_TOKEN) for chars in report["session_characters"])

    dev_passes = 2
    max_retries = 2
    attempts = max_retries + 1
    base_calls = dev_passes * dev_sessions + report_sessions
    paid_input = dev_passes * dev_input + report_input
    paid_expected = with_micro(block(paid_input, base_calls * 700, KIMI_PAID))
    paid_worst = with_micro(block(paid_input * attempts, base_calls * attempts * 2048, KIMI_PAID))

    report_calls = report["questions"] * 3
    answer_input_per_call = math.ceil(4096 / 4) + 500
    answer_expected = with_micro(block(report_calls * answer_input_per_call, report_calls * 150, KIMI_PAID))
    answer_worst = with_micro(block(report_calls * answer_input_per_call * attempts,
                                    report_calls * attempts * 512, KIMI_PAID))
    judge_input_per_call = 1200
    judge_expected = with_micro(block(report_calls * judge_input_per_call, report_calls * 200, DEEPSEEK_PEAK))
    judge_worst = with_micro(block(report_calls * judge_input_per_call * attempts,
                                   report_calls * attempts * 512, DEEPSEEK_PEAK))

    free_total_expected = round(answer_expected["usd"] + judge_expected["usd"], 6)
    free_total_worst = round(answer_worst["usd"] + judge_worst["usd"], 6)
    fallback_expected = round(paid_expected["usd"] + free_total_expected, 6)
    fallback_worst = round(paid_worst["usd"] + free_total_worst, 6)

    dev_paid_expected = with_micro(block(dev_passes * dev_input, dev_passes * dev_sessions * 700, KIMI_PAID))
    dev_paid_worst = with_micro(block(dev_passes * dev_input * attempts,
                                      dev_passes * dev_sessions * attempts * 2048, KIMI_PAID))

    def total(value):
        return {
            "usd": round(value, 6),
            "micro_usd": round(value * 1_000_000),
            "cny_at_7_1": round(value * USD_TO_CNY, 2),
        }

    return {
        "assumptions": {
            "extraction": {
                "channel": "OpenRouter free endpoint",
                "model": "moonshotai/kimi-k2.6:free",
                "dev_passes": dev_passes,
                "max_retries": max_retries,
                "attempts_per_session_in_worst_case": attempts,
                "prompt_tokens_per_call": 1000,
                "expected_output_tokens_per_call": 700,
                "max_output_tokens_per_call": 2048,
                "session_tokens": "ceil(session_characters / 3)",
                "note": (
                    "A third dev pass is not budgeted. If two passes do not freeze the prompt, "
                    "stop and request more budget instead of silently changing the protocol."
                ),
            },
            "answer": {
                "channel": "Moonshot paid API",
                "model": "kimi-k2.6",
                "arms": 3,
                "context_byte_budget": 4096,
                "bytes_per_token": 4,
                "prompt_tokens_per_call": 500,
                "expected_output_tokens_per_call": 150,
                "max_output_tokens_per_call": 512,
            },
            "judge": {
                "channel": "DeepSeek paid API",
                "model": "deepseek-flash",
                "different_vendor_from_answer": True,
                "prompt_tokens_per_call": judge_input_per_call,
                "expected_output_tokens_per_call": 200,
                "max_output_tokens_per_call": 512,
            },
            "prices": {
                "snapshot_date": "2026-10-24",
                "kimi_k2_6_paid_usd_per_mtok": KIMI_PAID,
                "deepseek_flash_peak_usd_per_mtok": DEEPSEEK_PEAK,
                "usd_to_cny": USD_TO_CNY,
                "note": "Prices exclude tax; cached-input discounts are not assumed.",
            },
        },
        "extraction": {
            "dev_sessions": dev_sessions,
            "report_sessions": report_sessions,
            "free_endpoint": {"usd": 0.0, "micro_usd": 0, "cny_at_7_1": 0.0},
            "paid_fallback_expected": paid_expected,
            "paid_fallback_worst": paid_worst,
            "paid_dev_only_expected": dev_paid_expected,
            "paid_dev_only_worst": dev_paid_worst,
            "base_calls": base_calls,
            "worst_case_calls": base_calls * attempts,
            "wall_clock_hours_at_30s": round(base_calls * 30 / 3600, 2),
            "wall_clock_hours_at_30s_worst": round(base_calls * attempts * 30 / 3600, 2),
            "wall_clock_note": "Excludes exponential-backoff sleeps after 429 responses.",
        },
        "answer": {
            "calls": report_calls,
            "expected": answer_expected,
            "worst_case": answer_worst,
            "wall_clock_hours_at_30s": round(report_calls * 30 / 3600, 2),
            "wall_clock_hours_at_30s_worst": round(report_calls * attempts * 30 / 3600, 2),
        },
        "judge": {
            "calls": report_calls,
            "expected": judge_expected,
            "worst_case": judge_worst,
            "wall_clock_hours_at_30s": round(report_calls * 30 / 3600, 2),
            "wall_clock_hours_at_30s_worst": round(report_calls * attempts * 30 / 3600, 2),
        },
        "totals": {
            "free_extraction_expected": total(free_total_expected),
            "free_extraction_worst_case": total(free_total_worst),
            "paid_fallback_expected": total(fallback_expected),
            "paid_fallback_worst_case": total(fallback_worst),
            "note": (
                "The expected free-path figure is answer + judge only. The paid fallback "
                "re-runs the full extraction plan (two dev passes plus report) through the "
                "paid Kimi endpoint if the free endpoint fails."
            ),
        },
    }


def audit(data_path, manifest_path):
    data_path = Path(data_path)
    manifest = load_json(manifest_path)
    actual_sha = sha256_file(data_path)
    actual_bytes = data_path.stat().st_size
    if actual_bytes != manifest["bytes"]:
        raise ValueError("dataset size %d != manifest %d" % (actual_bytes, manifest["bytes"]))
    if actual_sha != manifest["sha256"]:
        raise ValueError("dataset sha256 %s != manifest %s" % (actual_sha, manifest["sha256"]))
    records = load_json(data_path)
    validate(records)

    types = Counter(record["question_type"] for record in records)
    abs_records = [record for record in records if record["question_id"].endswith("_abs")]
    ku_records = [record for record in records if record["question_type"] == "knowledge-update"]
    question_chars = [sum(session_char_counts(record)) for record in records]
    question_sessions = [len(record["haystack_sessions"]) for record in records]
    question_turns = [sum(len(session) for session in record["haystack_sessions"]) for record in records]
    all_session_chars = [value for record in records for value in session_char_counts(record)]

    splits = build_splits(records)
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "evidence": "Stage 0 data audit and cost projection; no model calls were made.",
        "dataset": {
            "name": manifest["dataset"],
            "source": manifest["source"],
            "file": str(data_path.relative_to(HERE)),
            "bytes": actual_bytes,
            "sha256": actual_sha,
            "downloaded_at": manifest["downloaded_at"],
            "n_questions": len(records),
            "token_estimate": "ceil(characters / 3); not tokenizer output",
        },
        "scale": {
            "question_types": dict(sorted(types.items())),
            "knowledge_update": {
                "total": len(ku_records),
                "non_abstention": sum(1 for record in ku_records if not record["question_id"].endswith("_abs")),
                "abstention": sum(1 for record in ku_records if record["question_id"].endswith("_abs")),
            },
            "abstention": {
                "total": len(abs_records),
                "by_type": dict(sorted(Counter(record["question_type"] for record in abs_records).items())),
            },
            "haystack": {
                "total_sessions": sum(question_sessions),
                "total_turns": sum(question_turns),
                "total_characters": sum(question_chars),
                "estimated_tokens": sum(math.ceil(value / CHARS_PER_TOKEN) for value in all_session_chars),
                "characters_per_question": distribution(question_chars),
                "estimated_tokens_per_question": {
                    key: (round(value / CHARS_PER_TOKEN) if isinstance(value, (int, float)) else value)
                    for key, value in distribution(question_chars).items()
                },
                "sessions_per_question": distribution(question_sessions),
                "turns_per_question": distribution(question_turns),
                "characters_per_session": distribution(all_session_chars),
                "has_answer_turns": sum(
                    1 for record in records for session in record["haystack_sessions"]
                    for turn in session if turn.get("has_answer") is True),
                "answer_session_id_count": dict(sorted(Counter(
                    len(record["answer_session_ids"]) for record in records).items())),
            },
        },
        "splits": splits,
        "cost_projection": project_cost(splits),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    result = audit(args.data, args.manifest)
    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    scale = result["scale"]
    totals = result["cost_projection"]["totals"]
    splits = result["splits"]
    print("LongMemEval-S: %d questions, sha256 %s" % (
        result["dataset"]["n_questions"], result["dataset"]["sha256"]))
    print("KU total %d (non-abs %d, abs %d); abstention total %d" % (
        scale["knowledge_update"]["total"], scale["knowledge_update"]["non_abstention"],
        scale["knowledge_update"]["abstention"], scale["abstention"]["total"]))
    print("dev %d (KU %d + ABS %d); report %d (KU %d + ABS %d)" % (
        splits["dev"]["questions"], splits["dev"]["knowledge_update_non_abs"], splits["dev"]["abstention"],
        splits["report"]["questions"], splits["report"]["knowledge_update_non_abs"], splits["report"]["abstention"]))
    print("per-question haystack characters: median %d, p95 %d, max %d" % (
        scale["haystack"]["characters_per_question"]["median"],
        scale["haystack"]["characters_per_question"]["p95"],
        scale["haystack"]["characters_per_question"]["max"]))
    print("free extraction path: expected paid $%.4f (cny %.2f), worst-case paid $%.4f (cny %.2f)" % (
        totals["free_extraction_expected"]["usd"], totals["free_extraction_expected"]["cny_at_7_1"],
        totals["free_extraction_worst_case"]["usd"], totals["free_extraction_worst_case"]["cny_at_7_1"]))
    print("paid extraction fallback: expected $%.2f, worst-case $%.2f" % (
        totals["paid_fallback_expected"]["usd"], totals["paid_fallback_worst_case"]["usd"]))
    print("wrote %s" % out)


if __name__ == "__main__":
    main()
