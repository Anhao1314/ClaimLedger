"""LongMemEval session extraction: faithful claim transcription, resumable.

The extractor only transcribes verifiable statements from one session. It never
sees other sessions and never decides which statement replaces another; ingest
feeds claims to ``ClaimStore`` in haystack order and lets the store's lexical
conflict matcher surface updates. The benchmark therefore measures the store's
status policy, not an extractor's reconciliation judgment.

The default channel is OpenRouter's OpenAI-compatible endpoint with a free
``kimi-k2.6`` model. Keys come from the environment only and are never logged,
serialized, or written into fixtures.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from chat_distiller.claims import ClaimStore, ClaimStoreError, find_conflicts

PROMPT_VERSION = "lme-extract-v1"
PROMPT_DATE = "2026-10-24"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "moonshotai/kimi-k2.6:free"
DEFAULT_INTERVAL = 30.0
LOWERED_INTERVAL = 15.0
MAX_OUTPUT_TOKENS = 2048
MAX_RETRIES = 2
MAX_429_BACKOFFS = 3
BACKOFF_429 = (60, 120, 300)
BACKOFF_TRANSIENT = (30, 60)
MAX_CONSECUTIVE_FAILURES = 10
MAX_TEXT = 1000
MAX_QUOTE = 300
TOPICS = (
    "personal", "work", "preferences", "health", "travel", "finance",
    "relationships", "education", "technology", "other",
)
TOPIC_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
TAG_RE = re.compile(r"[a-z0-9][a-z0-9:_-]{0,39}\Z")
JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

SYSTEM_PROMPT = """You are a faithful transcription component for a decision ledger.
Read one conversation session and transcribe the user-specific, verifiable
statements into claims. You are not a summarizer, an inferencer, or a conflict
resolver.

Rules:
1. Extract only statements about the user's own life, facts, experiences,
   preferences, possessions, plans, relationships, work, health, or explicitly
   stated decisions and constraints.
2. Do not extract generic assistant knowledge, advice, definitions, opinions, or
   world facts. An assistant turn is eligible only when it explicitly restates a
   user fact; the quote must show that restatement.
3. Every claim must be directly supported by a verbatim quote from the session.
   The quote must be copied exactly, without paraphrase, and is at most 300
   characters. The claim text is a short standalone sentence of at most 1000
   characters; do not add information not present in the quote.
4. Transcribe updates as separate claims. If the user says "now I have four"
   after an earlier statement "I had three", emit both statements as separate
   claims. Never merge them, never decide which one is current, and never drop
   the older statement.
5. One claim per atomic fact. Split compound sentences when they contain
   independent facts. Do not duplicate the same fact.
6. For every turn that contains no eligible statement, list its zero-based
   index in skipped_turns. Do not invent a claim to increase coverage.
7. Use only this topic vocabulary: personal, work, preferences, health, travel,
   finance, relationships, education, technology, other.
8. tags: 1-4 short lowercase labels without spaces (letters, digits, hyphen,
   underscore, colon).
9. turn_indices: the zero-based indices of the turn(s) that support the claim.
10. Return one JSON object and nothing else:
{"claims":[{"text":"...","quote":"...","topic":"personal","tags":["..."],"turn_indices":[0]}],"skipped_turns":[1,2]}
If there are no eligible claims, return {"claims":[],"skipped_turns":[...]}.
Do not output Markdown fences, explanations, or commentary."""

SCHEMA_PROMPT = ('{"claims":[{"text":str,"quote":str,"topic":str,"tags":[str],'
                 '"turn_indices":[int]}],"skipped_turns":[int]}')
PROMPT_FINGERPRINT = hashlib.sha256(
    (SYSTEM_PROMPT + "\n" + SCHEMA_PROMPT).encode("utf-8")).hexdigest()


class ExtractionError(ValueError):
    """Invalid runner configuration or session metadata."""


class OutputError(ExtractionError):
    """The model returned content that does not match the JSON contract."""


class TransientError(ExtractionError):
    """A timeout, disconnect, or 5xx response worth retrying."""


class RateLimitError(ExtractionError):
    """HTTP 429; retry after the prescribed backoff."""


class FatalApiError(ExtractionError):
    """A non-retryable API error (bad key, bad request, wrong model)."""


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def sanitize_tag(value):
    value = str(value).strip().lower().replace(" ", "-")
    value = re.sub(r"[^a-z0-9:_-]", "-", value).strip("-")
    value = value[:40]
    return value if TAG_RE.fullmatch(value) else None


def clean_output(raw, turn_count):
    """Validate and normalize one model response; invalid claims are dropped."""
    if not isinstance(raw, dict):
        raise OutputError("response must be a JSON object")
    claims_raw = raw.get("claims")
    if not isinstance(claims_raw, list):
        raise OutputError("response.claims must be a list")
    skipped_raw = raw.get("skipped_turns", [])
    problems = []
    if not isinstance(skipped_raw, list):
        problems.append("skipped_turns was not a list")
        skipped_raw = []

    def valid_turns(value):
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            if isinstance(item, int) and not isinstance(item, bool) and 0 <= item < turn_count:
                if item not in out:
                    out.append(item)
        return out

    skipped = valid_turns(skipped_raw)
    claims = []
    covered = set()
    for index, claim in enumerate(claims_raw):
        if not isinstance(claim, dict):
            problems.append("claim %d is not an object" % index)
            continue
        text = " ".join(str(claim.get("text", "")).split())
        if not text:
            problems.append("claim %d has empty text" % index)
            continue
        if len(text) > MAX_TEXT:
            problems.append("claim %d text exceeds %d characters" % (index, MAX_TEXT))
            continue
        quote = claim.get("quote")
        if quote is not None and not isinstance(quote, str):
            problems.append("claim %d quote is not a string" % index)
            quote = None
        if quote is not None:
            quote = quote.strip()
            if len(quote) > MAX_QUOTE:
                problems.append("claim %d quote truncated to %d characters" % (index, MAX_QUOTE))
                quote = quote[:MAX_QUOTE]
            if not quote:
                quote = None
        topic = claim.get("topic")
        if topic not in TOPICS:
            problems.append("claim %d topic replaced with other: %r" % (index, topic))
            topic = "other"
        tags_raw = claim.get("tags", [])
        if not isinstance(tags_raw, list):
            problems.append("claim %d tags was not a list" % index)
            tags_raw = []
        tags = []
        for tag in tags_raw[:8]:
            cleaned = sanitize_tag(tag)
            if cleaned and cleaned not in tags:
                tags.append(cleaned)
        turn_indices = valid_turns(claim.get("turn_indices", []))
        if not turn_indices:
            problems.append("claim %d has no valid turn_indices" % index)
        covered.update(turn_indices)
        claims.append({
            "text": text,
            "quote": quote,
            "topic": topic,
            "tags": tags,
            "turn_indices": turn_indices,
        })

    overlap = sorted(set(skipped) & covered)
    if overlap:
        problems.append("turns both claimed and skipped: %s" % overlap)
        skipped = [item for item in skipped if item not in set(overlap)]
    unaccounted = sorted(set(range(turn_count)) - covered - set(skipped))
    return {
        "claims": claims,
        "skipped_turns": skipped,
        "coverage": {
            "turns": turn_count,
            "claimed_turns": len(covered),
            "skipped_turns": len(skipped),
            "unaccounted_turns": len(unaccounted),
            "unaccounted": unaccounted,
        },
        "problems": problems,
    }


def parse_output(content):
    if not isinstance(content, str) or not content.strip():
        raise OutputError("model returned empty content")
    text = JSON_FENCE_RE.sub("", content.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise OutputError("model response contains no JSON object")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise OutputError("model response is not valid JSON: %s" % exc) from exc


def build_messages(session_id, session_date, session):
    payload = {
        "session_id": session_id,
        "session_date": session_date,
        "turns": [
            {"index": index, "role": turn["role"], "content": turn["content"]}
            for index, turn in enumerate(session)
        ],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


class OpenRouterClient:
    """Minimal OpenAI-compatible chat client; standard library only."""

    name = "openrouter-free"

    def __init__(self, api_key, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL,
                 timeout=180):
        if not api_key:
            raise ExtractionError("LME_EXTRACT_API_KEY is not set")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, messages, *, max_tokens=MAX_OUTPUT_TOKENS, temperature=0.0):
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, method="POST",
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "HTTP-Referer": "https://github.com/Anhao1314/ClaimLedger",
                "X-Title": "ClaimLedger LongMemEval",
            })
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            latency = time.monotonic() - started
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            if exc.code == 429:
                error = RateLimitError("HTTP 429: " + detail)
                error.latency = latency
                raise error
            if 500 <= exc.code < 600:
                error = TransientError("HTTP %d: %s" % (exc.code, detail))
                error.latency = latency
                raise error
            raise FatalApiError("HTTP %d: %s" % (exc.code, detail)) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            error = TransientError("network error: %s" % exc)
            error.latency = time.monotonic() - started
            raise error from exc
        latency = time.monotonic() - started
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            error = TransientError("invalid API JSON: %s" % exc)
            error.latency = latency
            raise error from exc
        if isinstance(payload, dict) and payload.get("error"):
            message = str(payload["error"])[:500]
            error = FatalApiError("API error: " + message)
            error.latency = latency
            raise error
        try:
            choice = payload["choices"][0]
            content = choice["message"].get("content")
        except (KeyError, IndexError, TypeError) as exc:
            error = TransientError("API response missing choices[0].message.content")
            error.latency = latency
            raise error from exc
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str):
            error = TransientError("API response content is not text")
            error.latency = latency
            raise error
        if choice.get("finish_reason") == "length":
            error = OutputError("model output was truncated at max_tokens")
            error.latency = latency
            raise error
        return content, payload.get("usage") or {}, latency


class MockClient:
    """Deterministic offline client for pipeline tests; not for reported numbers."""

    name = "mock"
    model = "mock"
    is_mock = True

    def chat(self, messages, *, max_tokens=MAX_OUTPUT_TOKENS, temperature=0.0):
        payload = json.loads(messages[-1]["content"])
        claims = []
        skipped = []
        for turn in payload["turns"]:
            content = turn["content"].strip()
            if turn["role"] == "user" and len(content) >= 40:
                claims.append({
                    "text": content[:200],
                    "quote": content[:200],
                    "topic": "other",
                    "tags": ["mock"],
                    "turn_indices": [turn["index"]],
                })
            else:
                skipped.append(turn["index"])
        return json.dumps({"claims": claims, "skipped_turns": skipped}), {}, 0.0


class RunState:
    """Persistent counters, interval policy and progress log."""

    def __init__(self, path, *, split, prompt_version, model, channel,
                 interval=DEFAULT_INTERVAL, resume=True):
        self.path = Path(path)
        self.progress_path = self.path.with_name("progress.jsonl")
        if self.path.is_file() and resume:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if self.data.get("prompt_version") != prompt_version:
                raise ExtractionError(
                    "resume prompt version mismatch: %s vs %s"
                    % (self.data.get("prompt_version"), prompt_version))
            if self.data.get("model") != model:
                raise ExtractionError(
                    "resume model mismatch: %s vs %s" % (self.data.get("model"), model))
            if self.data.get("prompt_fingerprint") != PROMPT_FINGERPRINT:
                raise ExtractionError(
                    "resume prompt fingerprint mismatch; bump the prompt version "
                    "instead of reusing this run directory")
        else:
            self.data = {
                "schema_version": 1,
                "split": split,
                "prompt_version": prompt_version,
                "prompt_fingerprint": PROMPT_FINGERPRINT,
                "model": model,
                "channel": channel,
                "started_at": utc_now(),
                "updated_at": utc_now(),
                "interval_seconds": interval,
                "interval_checked": False,
                "interval_lowered": False,
                "interval_change": None,
                "calls": 0,
                "retries": 0,
                "http_429": 0,
                "failures": 0,
                "consecutive_failures": 0,
                "sessions_ok": 0,
                "sessions_skipped": 0,
                "sessions_failed": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latencies": [],
                "stop_reason": None,
            }
        self.last_call = None

    def save(self):
        self.data["updated_at"] = utc_now()
        atomic_write_json(self.path, self.data)

    def event(self, **value):
        value.setdefault("at", utc_now())
        append_jsonl(self.progress_path, value)

    def sleep_before_call(self, *, mock=False):
        if mock:
            return
        interval = float(self.data["interval_seconds"])
        if self.last_call is not None:
            wait = interval - (time.monotonic() - self.last_call)
            if wait > 0:
                time.sleep(wait)
        self.last_call = time.monotonic()

    def record_call(self, *, status, latency, usage=None):
        self.data["calls"] += 1
        self.data["latencies"] = (self.data["latencies"] + [round(float(latency), 3)])[-100:]
        if usage:
            self.data["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            self.data["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        self.event(event="call", status=status, latency=round(float(latency), 3))

    def record_429(self, backoff):
        self.data["http_429"] += 1
        self.event(event="429", backoff=backoff)

    def record_retry(self, reason):
        self.data["retries"] += 1
        self.event(event="retry", reason=reason)

    def record_session(self, ok, *, question_id, session_index, claims=0, skipped=0):
        if ok:
            self.data["sessions_ok"] += 1
            self.data["consecutive_failures"] = 0
        else:
            self.data["sessions_failed"] += 1
            self.data["failures"] += 1
            self.data["consecutive_failures"] += 1
        self.event(event="session", ok=ok, question_id=question_id,
                   session_index=session_index, claims=claims, skipped=skipped,
                   consecutive_failures=self.data["consecutive_failures"])

    def maybe_lower_interval(self):
        if self.data["interval_checked"] or self.data["calls"] < 50:
            return
        self.data["interval_checked"] = True
        latencies = self.data["latencies"][-20:]
        median = statistics.median(latencies) if latencies else 0
        allowed = (
            self.data["http_429"] == 0
            and self.data["failures"] == 0
            and len(latencies) >= 20
            and median > 0
            and max(latencies) <= 2 * median
        )
        self.event(event="interval_check", calls=self.data["calls"],
                   http_429=self.data["http_429"], failures=self.data["failures"],
                   median_latency=median, max_latency=max(latencies) if latencies else None,
                   allowed=allowed)
        if allowed:
            self.data["interval_seconds"] = LOWERED_INTERVAL
            self.data["interval_lowered"] = True
            self.data["interval_change"] = {
                "at": utc_now(), "from": DEFAULT_INTERVAL, "to": LOWERED_INTERVAL,
                "calls": self.data["calls"], "median_latency": median,
                "max_latency": max(latencies),
            }
            self.event(event="interval_changed", **self.data["interval_change"])


class ExtractionRunner:
    def __init__(self, records, split_ids, out_dir, client, *, prompt_version,
                 resume=True, max_sessions=None, question=None, split=None):
        self.records = {record["question_id"]: record for record in records}
        self.split_ids = [qid for qid in sorted(split_ids) if question is None or qid == question]
        self.out_dir = Path(out_dir)
        self.client = client
        self.prompt_version = prompt_version
        self.resume = resume
        self.max_sessions = max_sessions
        self.state = RunState(
            self.out_dir / "run_meta.json", split=split or self.out_dir.parent.name,
            prompt_version=prompt_version, model=getattr(client, "model", "mock"),
            channel=getattr(client, "name", "mock"))
        self.stop_path = self.out_dir / "STOP"

    def sessions(self):
        for question_id in self.split_ids:
            record = self.records[question_id]
            for index, (session_id, session_date, session) in enumerate(zip(
                    record["haystack_session_ids"], record["haystack_dates"],
                    record["haystack_sessions"])):
                yield question_id, index, session_id, session_date, session

    def session_path(self, question_id, index):
        return self.out_dir / "sessions" / ("%s__s%03d.json" % (question_id, index))

    def _valid_existing(self, path, question_id, index):
        if not path.is_file():
            return False
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return (value.get("schema_version") == 1
                and value.get("prompt_version") == self.prompt_version
                and value.get("prompt_fingerprint") == PROMPT_FINGERPRINT
                and value.get("question_id") == question_id
                and value.get("session_index") == index)

    def _call_with_backoff(self, messages):
        rate_limit_index = 0
        transient_index = 0
        while True:
            self.state.sleep_before_call(mock=getattr(self.client, "is_mock", False))
            try:
                return self.client.chat(messages)
            except RateLimitError as exc:
                self.state.record_call(status="429", latency=getattr(exc, "latency", 0))
                if rate_limit_index >= len(BACKOFF_429):
                    raise
                backoff = BACKOFF_429[rate_limit_index]
                rate_limit_index += 1
                self.state.record_429(backoff)
                time.sleep(backoff)
            except TransientError as exc:
                self.state.record_call(status="transient", latency=getattr(exc, "latency", 0))
                if transient_index >= len(BACKOFF_TRANSIENT):
                    raise
                backoff = BACKOFF_TRANSIENT[transient_index]
                transient_index += 1
                self.state.record_retry("transient")
                time.sleep(backoff)

    def extract_one(self, question_id, index, session_id, session_date, session):
        messages = build_messages(session_id, session_date, session)
        last_error = None
        for output_attempt in range(MAX_RETRIES + 1):
            try:
                content, usage, latency = self._call_with_backoff(messages)
            except OutputError as exc:
                last_error = str(exc)
                self.state.record_call(status="truncated",
                                       latency=getattr(exc, "latency", 0))
                self.state.record_retry("truncated")
                self.state.event(event="truncated_output", question_id=question_id,
                                 session_index=index, error=last_error[:300])
                continue
            except FatalApiError as exc:
                last_error = str(exc)
                self.state.record_call(status="fatal",
                                       latency=getattr(exc, "latency", 0))
                self.state.event(event="call_failed", question_id=question_id,
                                 session_index=index, error=last_error[:300])
                break
            except (TransientError, RateLimitError) as exc:
                last_error = str(exc)
                self.state.event(event="call_failed", question_id=question_id,
                                 session_index=index, error=last_error[:300])
                break
            try:
                raw = parse_output(content)
                cleaned = clean_output(raw, len(session))
            except OutputError as exc:
                last_error = str(exc)
                self.state.record_call(status="invalid_output", latency=latency,
                                       usage=usage)
                self.state.record_retry("invalid_output")
                self.state.event(event="invalid_output", question_id=question_id,
                                 session_index=index, error=last_error[:300])
                continue
            self.state.record_call(status="ok", latency=latency, usage=usage)
            output = {
                "schema_version": 1,
                "kind": "longmemeval-session-extraction",
                "prompt_version": self.prompt_version,
                "prompt_fingerprint": PROMPT_FINGERPRINT,
                "model": getattr(self.client, "model", "mock"),
                "channel": getattr(self.client, "name", "mock"),
                "question_id": question_id,
                "session_id": session_id,
                "session_index": index,
                "session_date": session_date,
                "claims": cleaned["claims"],
                "skipped_turns": cleaned["skipped_turns"],
                "coverage": cleaned["coverage"],
                "problems": cleaned["problems"],
                "usage": usage,
                "latency_seconds": round(latency, 3),
                "extracted_at": utc_now(),
            }
            return output
        self.state.event(event="session_failed", question_id=question_id,
                         session_index=index, error=(last_error or "unknown")[:300])
        return None

    def run(self):
        if self.stop_path.exists():
            raise ExtractionError(
                "STOP marker present at %s; review before resuming" % self.stop_path)
        processed = 0
        for question_id, index, session_id, session_date, session in self.sessions():
            if self.max_sessions is not None and processed >= self.max_sessions:
                self.state.data["stop_reason"] = "limit"
                break
            path = self.session_path(question_id, index)
            if self.resume and self._valid_existing(path, question_id, index):
                self.state.data["sessions_skipped"] += 1
                continue
            output = self.extract_one(question_id, index, session_id, session_date, session)
            if output is None:
                self.state.record_session(False, question_id=question_id, session_index=index)
                if self.state.data["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
                    self.state.data["stop_reason"] = "consecutive_failures"
                    self.stop_path.write_text(
                        json.dumps({"reason": "consecutive_failures",
                                    "at": utc_now(),
                                    "count": self.state.data["consecutive_failures"]},
                                   ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
                    self.state.event(event="stopped", reason="consecutive_failures")
                    break
            else:
                atomic_write_json(path, output)
                self.state.record_session(
                    True, question_id=question_id, session_index=index,
                    claims=len(output["claims"]), skipped=len(output["skipped_turns"]))
                processed += 1
            self.state.maybe_lower_interval()
            self.state.save()
        self.state.save()
        return {
            "calls": self.state.data["calls"],
            "sessions_ok": self.state.data["sessions_ok"],
            "sessions_skipped": self.state.data["sessions_skipped"],
            "sessions_failed": self.state.data["sessions_failed"],
            "http_429": self.state.data["http_429"],
            "retries": self.state.data["retries"],
            "interval_seconds": self.state.data["interval_seconds"],
            "stop_reason": self.state.data["stop_reason"],
        }


def load_session_outputs(out_dir, question_id):
    out_dir = Path(out_dir) / "sessions"
    outputs = []
    for path in sorted(out_dir.glob(question_id + "__s*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("question_id") != question_id:
            raise ExtractionError("output question mismatch: %s" % path)
        outputs.append(value)
    outputs.sort(key=lambda value: value["session_index"])
    return outputs


def ingest_question(record, outputs, store_path, prompt_version):
    store_path = Path(store_path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", ".audit.jsonl", ".lock"):
        candidate = store_path.with_name(store_path.name + suffix)
        if candidate.exists():
            candidate.unlink()
    store = ClaimStore(store_path)
    recorded = duplicates = errors = 0
    superseded = 0
    error_messages = []
    for output in outputs:
        session_id = output["session_id"]
        session_date = output.get("session_date") or ""
        for claim in output.get("claims", []):
            text = claim["text"]
            topic = claim.get("topic", "other")
            tags = ["lme", "prompt:" + prompt_version]
            for tag in claim.get("tags", []):
                cleaned = sanitize_tag(tag)
                if cleaned and cleaned not in tags:
                    tags.append(cleaned)
            quote = claim.get("quote")
            if quote:
                quote = quote[:MAX_QUOTE]
            conflicts = find_conflicts(text, store.claims(status="现行"))
            supersedes = [item["claim_id"] for item in conflicts] or None
            try:
                store.record(
                    text, topic=topic, tags=tags[:10],
                    source="%s/%s" % (record["question_id"], session_id),
                    quote=quote, session_hint=session_date[:300],
                    supersedes=supersedes)
            except ClaimStoreError as exc:
                message = str(exc)
                if "identical claim already exists" in message:
                    duplicates += 1
                else:
                    errors += 1
                    error_messages.append(message[:300])
                continue
            recorded += 1
            superseded += len(supersedes or [])
    meta = {
        "schema_version": 1,
        "question_id": record["question_id"],
        "prompt_version": prompt_version,
        "sessions": len(outputs),
        "claims": sum(len(output.get("claims", [])) for output in outputs),
        "recorded": recorded,
        "duplicates": duplicates,
        "superseded_claims": superseded,
        "errors": errors,
        "error_messages": error_messages[:20],
        "store_sha256": store.digest(),
    }
    atomic_write_json(store_path.with_suffix(".meta.json"), meta)
    return meta


def ingest_all(records, split_ids, out_dir, prompt_version):
    by_id = {record["question_id"]: record for record in records}
    summary = {}
    for question_id in sorted(split_ids):
        outputs = load_session_outputs(out_dir, question_id)
        meta = ingest_question(
            by_id[question_id], outputs,
            Path(out_dir) / "stores" / (question_id + ".jsonl"), prompt_version)
        summary[question_id] = meta
    atomic_write_json(Path(out_dir) / "ingest_summary.json", summary)
    return summary
