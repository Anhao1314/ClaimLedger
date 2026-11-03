# judge_bench_001 — is the judge a commodity?

**Protocol** [protocol.json](protocol.json) (frozen before any scored call)
**Fixture** the 60 adversarial pairs from [relation_002](../relation_002/pairs.jsonl)
**Runs** Jev ×5 · deepseek-flash ×6 (5 at t=1.0, 1 at t=0) · deepseek-v4-pro ×4 (3 at t=1.0, 1 at t=0)
**Question** the same contract `relation` question, verbatim, for every judge

---

## Results

| Judge | Accuracy | Range | Genuine flips | Error-only | Parse failures | Brier | p50 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Jev 1.14.0** | 0.933 | 0.93–0.93 | **0/60** | 2/60 | **0.67%** | 0.046 | **945 ms** |
| deepseek-flash (t=1.0) | 0.927 | 0.91–0.96 | 7/60 | 12/60 | 14.0% | **0.025** | 2,124 ms |
| deepseek-flash (t=0) | 0.959 | — | — | — | 18.3% | 0.042 | 2,102 ms |
| deepseek-v4-pro (t=1.0) | 0.973* | 0.95–1.00 | 2/60 | 20/60 | **40.0%** | 0.0† | 3,916 ms |
| deepseek-v4-pro (t=0) | 0.943* | — | — | — | 41.7% | 0.0† | 3,841 ms |

\* accuracy computed only over responses that parsed — for v4-pro that is 60% of calls.
† Brier 0.0 is **not good calibration**: 100% of v4-pro's parsed outputs are degenerate
(top probability ≥ 0.99), so the score reflects hard 1.0/0.0 guesses, not graded belief.

## What it shows

1. **Accuracy is roughly a tie between Jev and a general LLM judge.** 0.933 vs 0.927 at
   temperature 1.0. v4-pro's higher point estimate is on the 60% of calls it could answer —
   selection bias, not capability.

2. **Stability is not a tie.** Jev: **zero genuine label flips in 300 calls** (its two
   "unstable" pairs were transport errors, now separated out). deepseek-flash flips 7 of 60
   pairs across five identical runs — 11.7%. A judge that changes its answer on 1 in 8
   borderline pairs is not usable for governance without a margin rule.

3. **Schema reliability is not a tie.** Jev returns a typed distribution 99.3% of the time
   (2 transport failures, no schema failures). deepseek-flash fails to produce a parseable
   distribution on 14% of calls; deepseek-v4-pro on 40%.

4. **Calibration: Jev does not win this axis.** Brier 0.046 vs flash's 0.025. Star this —
   it contradicts the assumption that a purpose-built decision model is better calibrated
   here. Two caveats keep it from being a clean loss: flash is more overconfident
   (top-probability p10 = 0.90 vs Jev's 0.71) and it **bails on the 14% hardest cases**, so
   its Brier is computed on the subset it chose to answer. n=60 is too small to call either
   model calibrated.

5. **Latency: Jev is 2.2–4.1× faster** per call at equal or better reliability.

## The decision

`judge_is_commodity: false` — no DeepSeek arm matched Jev on stability **and** schema
reliability. But the honest summary is narrower than "Jev wins":

> **The judge is a commodity on accuracy and (apparently) calibration. It is not a commodity
> on stability and schema reliability — and those are the two properties a governance layer
> cannot work without.**

The architecture claim survives in either direction:

- Jev wins stability/schema → it is the right default for this pipeline.
- If a future model matches those, the pipeline is unaffected — the contract, two-stage
  policy, margin rule and sealed log do not reference the judge. This experiment is itself a
  demonstration of that: three different judges ran through the same question set, and every
  difference is measurable at the output.

## Limits

- Single fixture, single labeller, n=60.
- DeepSeek probabilities are self-reported, not trained-calibrated.
- Latency depends on network location; the ratio matters more than the absolute number.
- The parse-failure rate for v4-pro may be fixable with a stricter prompt or JSON schema;
  this run used a plain JSON instruction. As measured, it is not drop-in usable.