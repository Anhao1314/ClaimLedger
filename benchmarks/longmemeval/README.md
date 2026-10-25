# LongMemEval-S benchmark

Status: **Stage 0 approved. Stage 1 complete (free). Stage 2 pipeline implemented
and mock-tested; the real dev run awaits `LME_EXTRACT_API_KEY`. No paid calls.**
Work happens on `feat/longmemeval-benchmark`; nothing is merged into `main` until
the final numbers pass review. Because no extraction has started yet, the
free-endpoint policy applies from the first session; there is no paid extraction
work to preserve.

This benchmark moves ClaimLedger's headline retrieval result (stale hits 54% → 0
on the synthetic fixture) onto the public LongMemEval-S benchmark. The unit under
test is the claim store and its status policy, not a prompt trick: the extractor
only transcribes verifiable statements from each haystack session; conflict
judgment stays with `ClaimStore.find_conflicts` / `supersede` at ingest time.

## 1. Data and scale

### Source and verification

| Item | Value |
| --- | --- |
| Dataset | LongMemEval-S (cleaned), `xiaowu0162/longmemeval-cleaned` |
| URL | <https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json> |
| Local file | `benchmarks/longmemeval/data/longmemeval_s_cleaned.json` (gitignored) |
| Bytes | 277,383,467 |
| SHA-256 | `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` |
| Manifest | `benchmarks/longmemeval/data/manifest.json` |
| Downloaded | 2026-10-24T15:09:18Z |

The SHA-256 matches the Hugging Face `x-linked-etag` for the file. The manifest is
tracked; the 265 MiB data file is not. The first download attempt was reset by
HTTP/2; the retry used HTTP/1.1 and completed with the hash above.

```bash
curl --http1.1 -L --fail --retry 10 --retry-all-errors -C - \
  -o benchmarks/longmemeval/data/longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json
shasum -a 256 benchmarks/longmemeval/data/longmemeval_s_cleaned.json
.venv/bin/python benchmarks/longmemeval/stats.py
```

`stats.py` refuses to run if the size or SHA-256 differs from the manifest, then
writes `benchmarks/longmemeval/data-stats.json`.

### Question mix

All 500 questions are present.

| Question type | n |
| --- | ---: |
| multi-session | 133 |
| temporal-reasoning | 133 |
| knowledge-update (KU) | 78 |
| single-session-user | 70 |
| single-session-assistant | 56 |
| single-session-preference | 30 |
| **total** | **500** |

- **KU:** 78 total = 72 non-abstention + 6 with an `_abs` question id. The KU
  stratum used for stale-value metrics excludes all `_abs` questions.
- **Abstention:** 30 total (`question_id` ends with `_abs`): multi-session 12,
  single-session-user 6, temporal-reasoning 6, knowledge-update 6.

### Haystack size

| Metric | Value |
| --- | ---: |
| Sessions | 23,867 |
| Turns | 246,750 |
| Characters | 244,648,856 |
| Estimated tokens (`chars / 3`) | 81,557,552 |
| Turns marked `has_answer: true` | 896 |
| `answer_session_ids` length 1 / 2 / 3 / 4 / 5 / 6 | 176 / 250 / 41 / 19 / 11 / 3 |

Per question:

| Metric | min | p25 | median | p75 | p90 | p95 | max | mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| characters | 454,980 | 483,157 | 489,763 | 496,032 | 500,026 | 503,397 | 513,953 | 489,297.71 |
| est. tokens (`chars / 3`) | 151,660 | 161,052 | 163,254 | 165,344 | 166,675 | 167,799 | 171,318 | 163,099 |
| sessions | 38 | 45 | 48 | 50 | 52 | 53 | 62 | 47.73 |
| turns | 396 | 474 | 491 | 512 | 532 | 545 | 616 | 493.5 |

Characters per session: median 10,397, p95 18,238, max 78,117, mean 10,250.51.

**Token estimate caveat:** `chars / 3` is the conservative estimator requested for
stage 0, not tokenizer output. At a typical English ratio of ~4.2 characters per
token the median question is ~117k tokens, consistent with the ~115k-token
description of LongMemEval-S. The budget below deliberately uses the larger
`chars / 3` figure.

### Sampling (seed 42)

Pools: 72 KU non-abstention questions and 30 abstention questions. Sampling is
without replacement; dev and report are disjoint.

Algorithm: sort both pools by `question_id`; `random.Random(42).sample` in the order
dev KU → dev ABS → report KU → report ABS; sort each output; draw report from the
remainder.

| Split | KU (non-abs) | ABS | Total | Sessions | Turns | Characters | Est. tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dev | 20 | 10 | 30 | 1,434 | 14,743 | 14,691,132 | 4,897,498 |
| report | 40 | 20 | 60 | 2,864 | 29,691 | 29,306,946 | 9,769,931 |

- `dev.ids_sha256 = 915a47091ff8a1830176f3b1998b4b9360a35b65d7727b4e53c9d1c8610735bd`
- `report.ids_sha256 = 84c644b575de7ddb9a7d0cf988370d35dd75ebb3fd504adc54e00f3633af3ffa`
- Unused: 12 KU non-abstention questions, 0 abstention questions.
- All 30 abstention questions are used (10 dev + 20 report); the 6 KU `_abs`
  questions are evaluated only as abstention, never as KU.

**Leakage check:** 29 of the 30 `_abs` questions have a same-base question, but
none shares its `haystack_session_ids` with that base question (checked 0/29).
Base/abstention pairs therefore do not leak haystack content across a dev/report
boundary. The split remains disjoint at the question-id level.

## 2. Stage 1 smoke (free)

Five dev KU questions were retrieved at session granularity with three
tokenizers: `legacy` (the package's current `features()`), `word` (lowercased
word tokens), and `char4` (character 4-grams inside word tokens). Ground truth is
`answer_session_ids`; the shared metrics module is `benchmarks/metrics.py`.

Questions: `031748ae`, `06db6396`, `07741c44`, `08e075c7`, `184da446`.

| Tokenizer | Recall@1 | Recall@3 | Recall@5 | MRR |
| --- | ---: | ---: | ---: | ---: |
| legacy | 0.3000 | 0.7000 | 0.9000 | 0.8000 |
| word | 0.3000 | 0.7000 | 0.9000 | 0.8000 |
| char4 | 0.5000 | 1.0000 | 1.0000 | 1.0000 |

Findings:

- `legacy` and `word` are identical on English. The current `features()` already
  tokenizes Latin text as `[a-z0-9]+` words; only Chinese gets character bigrams.
  The premise that the current scorer is character-level for English does not
  hold, so no core-library change is justified by this smoke.
- `char4` scored higher on these five questions, but n=5 is far too small to
  choose a tokenizer. It stays available as an evaluation-adapter option, not as
  the default; the report split is not used for tokenizer selection.
- The adapter keeps both language paths explicit (`legacy` handles Chinese bigrams
  and English words; `word`/`char4` are English-oriented). Core `chat_distiller`
  remains dependency-free.

This is a retrieval-only smoke, not the three-arm LongMemEval result. Full output:
`benchmarks/longmemeval/smoke.json`.

## 3. Cost projection (approval requested)

### Channel and model split

| Stage | Channel | Model | Price (USD / MTok) |
| --- | --- | --- | --- |
| Extraction | OpenRouter free endpoint | `moonshotai/kimi-k2.6:free` | $0 (free) |
| Answer | Moonshot paid API | `kimi-k2.6` | input $0.95, output $4.00, cached input $0.16 |
| Judge | DeepSeek paid API | `deepseek-flash` | peak input $0.30, output $1.20 (off-peak half) |

Extraction and answer request the same model family, `kimi-k2.6`; only the serving
channel differs. The methods section of the final report will state this channel
split explicitly: extraction is to run through the OpenRouter free endpoint,
answer through the Moonshot paid API. Because both request the same model id, the
design treats extraction quality as equivalent; provider/routing differences on
the free channel are disclosed as a limitation, not a reason to switch models
mid-run. The judge is a different vendor from the answer model.

Prices are a 2026-10-24 snapshot from
`https://platform.kimi.ai/docs/pricing/chat` and
`https://api-docs.deepseek.com/quick_start/pricing`; tax excluded, cached-input
discounts not assumed. USD→CNY uses 7.1 only for the ¥5 sanity target.

Environment contract (keys are injected by the Host; none is written to disk):

| Variable | Default / purpose |
| --- | --- |
| `LME_EXTRACT_BASE_URL` | `https://openrouter.ai/api/v1` |
| `LME_EXTRACT_API_KEY` | OpenRouter key, required for free extraction |
| `LME_EXTRACT_MODEL` | `moonshotai/kimi-k2.6:free` |
| `KIMI_API_KEY` | Moonshot paid key, required for answers |
| `LME_ANSWER_BASE_URL` | `https://api.moonshot.cn/v1` |
| `LME_ANSWER_MODEL` | `kimi-k2.6` |
| `LME_JUDGE_API_KEY` | DeepSeek key, required for judging |
| `LME_JUDGE_BASE_URL` | `https://api.deepseek.com/v1` |
| `LME_JUDGE_MODEL` | `deepseek-flash` |

### Assumptions

- Extraction is one call per haystack session. Dev gets **2 passes** (prompt
  development + freeze); report gets **1 pass**. A third dev pass is not budgeted:
  stop and request more budget if two passes do not freeze the prompt.
- Every session may be retried at most twice (3 attempts total) on timeout,
  truncation, or invalid JSON; all attempts are counted and disclosed.
- Per extraction call: 1,000 prompt tokens; session tokens = `ceil(chars / 3)`;
  expected output 700 tokens; hard max 2,048 tokens.
- Answer: 3 arms × 60 report questions = 180 calls; 4 KiB context (~1,024 tokens),
  500 prompt tokens; expected output 150 tokens; max 512.
- Judge: 180 calls; 1,200 input tokens; expected output 200 tokens; max 512.
- Rate discipline: one concurrent call, ≥30 s between calls, 429 backoff at
  60/120/300 s (max three). Wall-clock figures below exclude backoff sleeps.
- Failure stop rule: if 10 consecutive sessions fail, the run stops and reports;
  it does not silently switch models, providers, or to a smaller model.
- Retry, backoff, failure and resume counts are recorded per session and
  summarised in the final report.

### Projection

| Segment | Base calls / worst calls | Expected USD (µUSD) | Worst-case USD (µUSD) | Expected CNY |
| --- | --- | ---: | ---: | ---: |
| Extraction (free endpoint) | 5,732 / 17,196 | $0 (0) | $0 (0) | ¥0 |
| Answer | 180 / 540 | $0.368604 (368,604) | $1.887732 (1,887,732) | ¥2.62 |
| Judge | 180 / 540 | $0.108000 (108,000) | $0.526176 (526,176) | ¥0.77 |
| **Free-path total** | | **$0.476604 (476,604)** | **$2.413908 (2,413,908)** | **¥3.38** |

The expected free-path total is **$0.48 / ¥3.38**, under the ¥5 target. The
worst-case cap is **$2.42 / ¥17.14**.

Wall clock at one call per 30 s:

| Segment | Expected | Worst case |
| --- | ---: | ---: |
| Extraction | 47.77 h | 143.3 h |
| Answer | 1.5 h | 4.5 h |
| Judge | 1.5 h | 4.5 h |
| **Total** | **~50.8 h** | **~152.3 h** |

These figures exclude 429 backoff sleeps and ordinary network latency; they are
arithmetic from the call counts, not a schedule promise.

### Paid extraction fallback (not pre-approved)

If the free endpoint fails mid-run, the conservative fallback is to re-run the
whole extraction plan on the paid Kimi API:

| Fallback | Expected USD (µUSD) | Worst-case USD (µUSD) | Expected CNY |
| --- | ---: | ---: | ---: |
| Extraction only | $40.081681 (40,081,681) | $212.965874 (212,965,874) | ¥284.58 |
| With answer + judge | $40.558285 (40,558,285) | $215.379782 (215,379,782) | ¥287.96 |

If no OpenRouter key is available, the smaller fallback is to run **dev only** on
the paid endpoint to keep pipeline development moving: $20.060246 expected /
$106.573507 worst (¥142.43 / ¥756.67). Report extraction waits for the free key.
No paid fallback starts without a new approval.

### Approval requested

- Approve the free extraction path plus the paid answer/judge cap of **$2.42
  (¥17.14)**; expected spend **$0.48 (¥3.38)**.
- Provide `LME_EXTRACT_API_KEY` (OpenRouter) at run time. Keys are read from the
  environment only; they are never written to a file, log, fixture, or claim.
- The paid extraction fallback above is informational and **not** part of this
  approval. If the free endpoint fails, the run stops and reports.

At stage 0 none of the three key variables was present in the shell; no key was
read or echoed.

## 4. Planned execution commands

**Implementation status.** `extraction.py` implements the JSON contract, per-session
resume, 30 s→15 s interval policy, 429/transient/invalid-output accounting, the
10-consecutive-failure stop, chronological ingest, and `find_conflicts` +
`supersede`. A mock run over the full dev split processed **1,434/1,434 sessions**
and ingested 30 stores with **0 errors** (7,015 mock claims, 25 duplicates, 663
superseded). Mock output is a pipeline check only and is not reportable. The real
dev run needs `LME_EXTRACT_API_KEY`; the key is not present in the tool shell.

Scripts for stages 2–5 are in place or planned as follows; stage 0 and stage 1
commands are already runnable.

```bash
# Stage 0 — done
.venv/bin/python benchmarks/longmemeval/stats.py

# Stage 1 — free retrieval smoke, dev 5 questions
.venv/bin/python benchmarks/longmemeval/smoke.py --split dev --n 5 \
  --out benchmarks/longmemeval/smoke.json

# Stage 2 — paid-free extraction (dev only until the prompt is frozen)
# Host injects LME_EXTRACT_API_KEY into the process environment; never create a .env.
export LME_EXTRACT_BASE_URL="https://openrouter.ai/api/v1"
export LME_EXTRACT_MODEL="moonshotai/kimi-k2.6:free"
.venv/bin/python benchmarks/longmemeval/extract.py --split dev --pass 1 --resume
# revise the prompt on dev only, then:
.venv/bin/python benchmarks/longmemeval/extract.py --split dev --pass 2 --resume
# freeze prompt version + date + dev metrics here; report split is now closed to changes
.venv/bin/python benchmarks/longmemeval/extract.py --split report --resume

# Stage 3 — free three-arm retrieval evaluation
.venv/bin/python benchmarks/longmemeval/retrieval_eval.py --split report \
  --arms baseline,structured,status-aware

# Stage 4 — paid answers and judge
export KIMI_API_KEY          # injected by Host, never echoed
export LME_ANSWER_BASE_URL="https://api.moonshot.cn/v1"
export LME_ANSWER_MODEL="kimi-k2.6"
.venv/bin/python benchmarks/longmemeval/answer.py --split report
export LME_JUDGE_API_KEY     # injected by Host, never echoed
export LME_JUDGE_BASE_URL="https://api.deepseek.com/v1"
export LME_JUDGE_MODEL="deepseek-flash"
.venv/bin/python benchmarks/longmemeval/judge.py --split report

# Stage 5 — results and human-readable report
.venv/bin/python benchmarks/longmemeval/report.py

# Regression suite
.venv/bin/python -m unittest discover -s tests -v
```

## 5. Method notes and non-goals

- **Extraction is faithful transcription only.** The extractor may copy a
  verifiable statement, its source session and a quote. It must not decide that a
  newer statement replaces an older one; `ClaimStore.record` raises the conflict
  and the ingest step resolves it with `supersede` or `dispute`.
- **Dev/report discipline.** Prompt edits are allowed only against dev. Once
  frozen, the prompt version, date and dev metrics go into the report; the report
  split is never re-tuned.
- **Subset, not the full benchmark.** The final report will say
  "LongMemEval-S KU/ABS subset, n=60 report questions" and will not claim the full
  500-question benchmark. Cross-paper numeric comparisons are out of scope because
  judge and configuration differ.
- **Retrieval ground truth** is `answer_session_ids`; the three arms reuse the
  synthetic benchmark's definitions and `metrics()` semantics through a shared
  module, not a copied fork.
- **Stale-answer rate** is a deterministic rule over the gold answer and the old
  and new values in the haystack; it is the public counterpart of the 54% → 0
  story and will be reported separately from judge correctness.
- **Abstention** is reported as a separate correct-refusal rate; abstention
  questions have no positive `answer_session_ids` and are not folded into KU
  retrieval recall.

## 6. Provenance

- Dataset card: <https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned>
- Paper: LongMemEval, ICLR 2025 — <https://arxiv.org/abs/2410.10813>
- Audit output: `benchmarks/longmemeval/data-stats.json`
- Data manifest: `benchmarks/longmemeval/data/manifest.json`
- Stage 0 verification: `python -m unittest discover -s tests` → **402 tests, OK**
  (399 existing + 3 new sampler/budget tests). No existing test was removed.

Upstream dataset terms apply; the data file is not redistributed in this
repository.
