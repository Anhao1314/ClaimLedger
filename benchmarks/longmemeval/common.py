"""LongMemEval data access, session text and lexical tokenizer variants.

The variants exist to test the retrieval adapter, not to change the package's
core: ``legacy`` is the package's current feature function (word tokens for
Latin text plus Chinese bigrams), ``word`` is a plain lowercased word split, and
``char4`` is a character 4-gram variant. All are deterministic and dependency
free.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "longmemeval_s_cleaned.json"
STATS = HERE / "data-stats.json"
WORD_RE = re.compile(r"[a-z0-9]+")


def load_records(path=DATA):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_stats(path=STATS):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def records_by_id(records):
    return {record["question_id"]: record for record in records}


def session_text(session):
    """One retrieval document per haystack session, roles preserved."""
    return "\n".join("%s: %s" % (turn["role"], turn["content"]) for turn in session)


def legacy_features(text):
    from chat_distiller._internal.query_memory import features

    return features(text)


def word_features(text):
    return set(WORD_RE.findall(str(text).lower()))


def char_features(text, n=4):
    """Character n-grams within word tokens; short tokens stay whole."""
    out = set()
    for token in WORD_RE.findall(str(text).lower()):
        if len(token) <= n:
            out.add(token)
        else:
            out.update(token[index:index + n] for index in range(len(token) - n + 1))
    return out


TOKENIZERS = {
    "legacy": legacy_features,
    "word": word_features,
    "char4": lambda text: char_features(text, 4),
}


def score(query, document, tokenizer):
    query_features = tokenizer(query)
    if not query_features:
        return 0.0
    document_features = tokenizer(document)
    shared = query_features & document_features
    if not shared:
        return 0.0
    return round(len(shared) / math.sqrt(max(1, len(document_features))), 8)


def rank_sessions(query, session_ids, sessions, tokenizer, top_k=5):
    if type(top_k) is not int or not 1 <= top_k <= 100:
        raise ValueError("top_k must be an integer between 1 and 100")
    scored = []
    for session_id, session in zip(session_ids, sessions):
        value = score(query, session_text(session), tokenizer)
        if value > 0:
            scored.append((value, session_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [{"session_id": session_id, "score": value}
            for value, session_id in scored[:top_k]]


def retrieval_runs(records, question_ids, tokenizer, top_k=5):
    by_id = records_by_id(records)
    runs = []
    for question_id in question_ids:
        record = by_id[question_id]
        expected = list(record["answer_session_ids"])
        if not expected:
            raise ValueError("question has no answer session ids: %s" % question_id)
        ranked = rank_sessions(
            record["question"], record["haystack_session_ids"],
            record["haystack_sessions"], tokenizer, top_k=top_k)
        runs.append({
            "case_id": question_id,
            "ids": [item["session_id"] for item in ranked],
            "expected": expected,
            "scores": [item["score"] for item in ranked],
        })
    return runs


def first_relevant_rank(ranked_ids, expected):
    expected = set(expected)
    for index, session_id in enumerate(ranked_ids, 1):
        if session_id in expected:
            return index
    return None


def select_smoke_questions(records, stats, n=5):
    """First n dev KU non-abstention questions, sorted for reproducibility."""
    dev_ids = set(stats["splits"]["dev"]["ids"])
    by_id = records_by_id(records)
    candidates = sorted(
        question_id for question_id in dev_ids
        if by_id[question_id]["question_type"] == "knowledge-update"
        and not question_id.endswith("_abs"))
    if len(candidates) < n:
        raise ValueError("not enough dev KU questions for smoke: %d" % len(candidates))
    return candidates[:n]
