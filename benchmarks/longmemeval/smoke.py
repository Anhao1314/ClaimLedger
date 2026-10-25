#!/usr/bin/env python3
"""Stage 1: English retrieval smoke on a fixed dev slice; no model calls.

Compares the package's current feature function (``legacy``), a plain lowercased
word tokenizer, and a character 4-gram tokenizer at session granularity. Ground
truth is ``answer_session_ids``. The shared metrics module is the same one the
synthetic benchmark uses.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "benchmarks"))

import common
from metrics import metrics

OUT = HERE / "smoke.json"
MODE_NOTES = {
    "legacy": "package features(): [a-z0-9]+ words plus Chinese bigrams",
    "word": "lowercase [a-z0-9]+ word tokens",
    "char4": "character 4-grams within lowercased word tokens",
}


def evaluate(records, stats, n=5, top_k=5):
    question_ids = common.select_smoke_questions(records, stats, n=n)
    result = {
        "schema_version": 1,
        "stage": "stage-1-english-retrieval-smoke",
        "evidence": "free session-level lexical retrieval; no model calls",
        "split": "dev",
        "question_ids": question_ids,
        "top_k": top_k,
        "tokenizers": {},
    }
    for name, tokenizer in common.TOKENIZERS.items():
        runs = common.retrieval_runs(records, question_ids, tokenizer, top_k=top_k)
        cases = []
        by_id = common.records_by_id(records)
        for run in runs:
            record = by_id[run["case_id"]]
            text_by_id = dict(zip(
                record["haystack_session_ids"],
                (common.session_text(session) for session in record["haystack_sessions"])))
            cases.append({
                "question_id": run["case_id"],
                "expected_session_ids": run["expected"],
                "ranked_session_ids": run["ids"],
                "scores": run["scores"],
                "first_relevant_rank": common.first_relevant_rank(run["ids"], run["expected"]),
                "retrieved_characters": sum(
                    len(text_by_id[session_id]) for session_id in run["ids"]
                    if session_id in text_by_id),
            })
        result["tokenizers"][name] = {
            "note": MODE_NOTES[name],
            "metrics": metrics(runs, statuses={}),
            "cases": cases,
        }
    return result


def markdown(result):
    keys = ["Recall@1", "Recall@3", "Recall@5", "MRR"]
    lines = [
        "# Stage 1 English retrieval smoke",
        "",
        result["evidence"],
        "",
        "Questions: " + ", ".join(result["question_ids"]),
        "",
        "| Tokenizer | " + " | ".join(keys) + " |",
        "| --- | " + " | ".join(["---"] * len(keys)) + " |",
    ]
    for name, value in result["tokenizers"].items():
        lines.append("| %s | %s |" % (name, " | ".join(
            "%.4f" % value["metrics"][key] for key in keys)))
    lines += ["", "| Tokenizer | Question | First relevant rank | Top-5 session ids |",
              "| --- | --- | ---: | --- |"]
    for name, value in result["tokenizers"].items():
        for case in value["cases"]:
            lines.append("| %s | %s | %s | %s |" % (
                name, case["question_id"], case["first_relevant_rank"] or "miss",
                ", ".join(case["ranked_session_ids"]) or "(none)"))
    lines += ["", "Stage 1 is retrieval-only and uses 5 dev questions; it is not the "
              "three-arm LongMemEval result."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=str(common.DATA))
    parser.add_argument("--stats", default=str(common.STATS))
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    result = evaluate(common.load_records(args.data), common.load_stats(args.stats),
                      n=args.n, top_k=args.top_k)
    Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(markdown(result))


if __name__ == "__main__":
    main()
