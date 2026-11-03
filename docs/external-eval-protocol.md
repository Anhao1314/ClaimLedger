# External blind evaluation protocol — relation_003

**Purpose:** test whether the judge result replicates when the builder is not the
grader and the sample is large enough to support a claim.

The existing relation_002 run is 60 pairs authored and graded inside this repo.
It is useful as an internal signal, not as external evidence. This protocol is
the external version.

## Roles (separated on purpose)

| Role | May do | May not do |
| --- | --- | --- |
| Builder | write code, freeze the protocol, run models | author or label pairs |
| Grader A / B | label pairs independently | see model outputs or each other's labels |
| Adjudicator | resolve A/B disagreements | run models or change the protocol |
| Auditor | check hashes, counts, and compliance | label pairs |

The builder and the grader must not be the same person. If only one person is
available, the evaluation is not external; label it as such.

## Hypotheses (pre-registered)

Primary endpoint: **accuracy on the frozen 240-pair set**.

- **H1 Accuracy.** Jev beats the lexical baseline by ≥20 percentage points.
- **H2 Stability.** Genuine label flips across 5 runs ≤5% of pairs.
- **H3 Parse.** Unparseable responses ≤2% of calls.
- **H4 Calibration (secondary).** Brier score no worse than a general LLM judge.

H1 is the only confirmatory test. H2–H4 are reported with confidence intervals
and labeled secondary.

## Sampling

- 240 pairs: 60 easy, 60 hard-negative, 60 hard-positive, 60 subtle/contradiction.
- Source: public corpora or decision logs from at least 3 external repositories,
  with written permission. No pair authored by the builder.
- Each pair is one sentence pair plus the frozen relation question.
- Stratify by domain; record the source and stratum for every pair.
- Write `pairs.jsonl`, then `sha256sum` it and put the hash in the protocol
  before any model call.

## Labeling

1. Each pair is labeled independently by Grader A and Grader B as
   `contradiction` / `complementary` / `unrelated`.
2. Report raw agreement and Cohen's κ.
3. Disagreements go to the Adjudicator, who sees both labels and the pair, and
   writes a one-line rationale. The adjudicated label is the ground truth.
4. Graders never see model outputs, prompts, or each other's labels.

## Runs

- Models: Jev, one general LLM judge (current flash model), one stronger model if
  available, and the lexical baseline.
- 5 runs per model, temperature fixed at the provider default or 0 where
  supported; same prompts; pair order shuffled with a recorded seed.
- Store every raw response under `runs/<model>/<run>/`.
- No prompt, threshold, or pair changes after the hash is frozen. Any change is a
  new protocol version and a new run.

## Metrics

- Accuracy with Wilson 95% confidence interval.
- Paired bootstrap (10,000 resamples) for each model difference; report the CI,
  not only the point estimate.
- Flip rate: pairs whose label changes across runs / total pairs.
- Parse failure rate, latency p50/p95, cost per 1,000 judgments.
- Brier score and reliability buckets where probabilities exist.
- Per-stratum accuracy, pre-registered; any other subgroup is exploratory.

## Prohibited after freeze

- adding, removing, or relabeling pairs;
- tuning prompts, thresholds, or policy after seeing results;
- dropping failed runs or parse failures from the denominator;
- reporting the best run instead of the mean and its interval;
- presenting an exploratory subgroup as confirmatory.

## Decision rule

Ship the claim only if:

1. the lower bound of the H1 accuracy CI is above lexical + 20pp, and
2. the H2 flip rate is ≤5%.

Otherwise publish the negative result and keep the README wording at
"not externally validated". A failed replication is a result, not a setback to
hide.

## Artifacts

```
experiments/relation_003/
  protocol.md          this document + frozen hashes
  pairs.jsonl          the 240 pairs
  labels.csv           adjudicated labels + A/B agreement
  runs/                raw model responses
  analysis.py          deterministic analysis
  results.json         metrics + CIs
  results.md           the readable report
  signoff.md           builder / grader / auditor signatures and dates
```

## Timeline

- Week 1: sampling and labeling; freeze hashes.
- Week 2: runs (5 per model).
- Week 3: analysis and report; no code changes to the judge during the run.

## What this does not prove

Even a successful run does not prove the system is useful in daily work. It
proves the judge makes the stated relation calls on this frozen set. Usability is
covered by [usage-protocol.md](usage-protocol.md).