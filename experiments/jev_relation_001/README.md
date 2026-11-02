# jev_relation_001 — can Jev tell contradiction from coincidence?

**Protocol** `protocol.json` (frozen 2026-11-02T21:40:00Z, before any scored call)
**Pairs** `pairs.jsonl` — 30 pairs: 10 contradiction, 10 complementary, 10 unrelated
**Run** `scripts/jev_relation_eval.py` → `results.json`

---

## Result

```
contradiction recall : 100.00%  (10/10)   gate ≥ 70%
false suppression    :   0.00%  (0/20)    gate ≤ 10%
accuracy             : 100.00%  (29/29 scored)
latency              : median 1276 ms, max 7274 ms
errors               : 1 (P15, 60 s timeout)
GATE                 : PASS
```

Confusion matrix over the 29 scored pairs:

| expected ↓ / observed → | contradiction | complementary | unrelated |
|---|---:|---:|---:|
| contradiction | **10** | 0 | 0 |
| complementary | 0 | **9** | 0 |
| unrelated | 0 | 0 | **10** |

The lexical blind spot was included on purpose: P02 is
`PostgreSQL is banned for this service` vs `Use PostgreSQL for all storage` —
high token overlap, opposite meaning. It was judged `contradiction` with
confidence 1.00.

## What this does NOT prove

- **The pairs were written by one person, in this project's own vocabulary.**
  The 100% is agreement with my own labelling, not with an independent judge.
- **The set is too easy to be decisive.** Labels follow a clean schema
  (`must` / `must not`, `only` / `any`); a strong model matching surface
  patterns would score the same.
- **n=30 cannot support calibration claims.** Confidence ranged 0.53–1.00 with
  median 0.98; that is a statement about this set, not about the model.
- **One transport failure at 60 s** means coverage is 29/30 = 96.7%. The gate
  was computed on covered pairs. On the worst-case reading (error counted as a
  miss) accuracy is 96.67%, recall still 100%, false suppression still 0%.

## What it does establish

1. The task is **not** beyond the model: it separates contradiction from
   complement from coincidence, including where word overlap misleads.
2. The **cost structure is workable**: ~1.3 s median per pair, one question per
   request. The earlier 11 s figure came from a 10-question request, which
   confirms that question count, not pair count, drives latency.
3. A **3.3% transport failure rate** exists and must be handled by policy, not
   by hope. The decision layer now fails **open to review** (`on_error="review"`):
   a model outage must never look like a confident exclusion.

## Next, if this direction continues

The gate is cleared, but the evidence is weak. The next run must fix the two
structural weaknesses:

- pairs sourced **independently** (public post-mortems, real migration notes),
  not authored here;
- an **adversarial** subset: pairs that look contradictory but are not (scoped
  exceptions), and pairs that look compatible but are not (version drift).

Reaching 100% again on that set would mean something. Reaching 100% on this one
means the plumbing works.