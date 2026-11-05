# e2e_003 Protocol — RAG, judged: embedding retrieval meets the governance layer

Frozen: 2026-11-05. **Run window opens after real_use_001 closes (2026-11-19).**
No edits after the first call. This protocol freezes hypotheses, arms, gates,
and the inheritance rule before any embedding is computed.

## Question

Two questions, one experiment:

1. What does pure RAG (embedding retrieval, stuffed context) do on this corpus —
   specifically on the conflict strata where judged briefs discriminate?
2. Does composing embedding retrieval WITH the governance layer (judge → relation
   → edge → packed brief) fix the lexical selector's known recall gap without
   losing conflict capture?

## Inheritance rule (frozen)

Tasks, records, checkers, system prompt, and the A/B/C/D arms are **inherited
verbatim from e2e_002 v8** (freeze.json, sha256-pinned). Their committed
run-1 results are reused as-is — no rerun:

| Arm | e2e_002 v8 overall | conflict strata (explicit+natural) |
| --- | --- | --- |
| A no memory | 0.525 | 0/10 |
| B all records verbatim | 0.925 | 10/10 |
| C judged brief (lexical) | 0.875 | 9/10 |
| D length-matched irrelevant | 0.525 | 1/10 |

Justification: identical frozen inputs and identical question set; judge
stability across days is expected from borderline-stability (unambiguous pairs
never flip) and is itself disclosed as a threat. Sanity anchor: F's
lexical-substrate selections must reproduce C's frozen candidate sets whenever
the embedding channel adds nothing; a mechanical diff is reported.

## New arms

- **E — pure RAG**: embed all 55 records + task with a frozen multilingual
  model (sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2`,
  l2-normalized cosine; model name and version hash recorded in results).
  Top-5 by cosine, byte-capped at the same 2048 budget, rendered in the same
  memory-block position. No judgment layer. This is the RAG baseline.
- **F — composition**: candidates = union(lexical hits, embedding top-6),
  capped at 6 → the full judgment pipeline (admit → pairwise relation → edge
  cascade → governing) → packed brief. Identical to C except the candidate
  channel.
- Runs: 3 runs per task per new arm, temperature 0, same model
  (deepseek-flash), same checkers. Primary = run 1.

## New frozen probe: cross-lingual recall (8 tasks)

The v8 corpus is English-task × English-record, where the lexical selector
already works — F's predicted advantage would be invisible there. Eight
**Chinese-phrased** tasks are added, each derived from an existing v8
constraint record (one per stratum-relevant record family: storage, retries,
logging, API keys, deployment, margin wording, console scope, benchmark
rigor), each with a language-independent code checker copied from the v8
checker style. Author overlap with the designer is disclosed (threat 1).
Probe runs: 8 tasks × 3 runs × {C, E, F}.

## Hypotheses and gates (pre-registered)

| # | Hypothesis | Gate |
| --- | --- | --- |
| E3-H1 | E is a sane RAG baseline (pipeline validity) | E overall ≥ 0.65; below this, E is invalid and conclusions stop |
| E3-H2 | **Pure RAG is conflict-blind on this corpus** | E conflict-total ≤ 6/10 AND strictly < C's 9/10 |
| E3-H3 | F is non-inferior to C overall | F overall ≥ 0.825 (C − 5pp), Wilson CI reported |
| E3-H4 | F keeps conflict capture | F conflict-total ≥ 8/10 |
| E3-H5 | F fixes the lexical recall gap | probe: F ≥ 5/8 AND C ≤ 3/8 |
| E3-H6 | directional, no gate: probe behavior of E (recall without governance may pass probe strata while still failing conflict strata — the two axes are independent), stability across runs, token costs, latency | report |

## Costs (frozen estimate)

E: 120 generation calls. F: 120 generation + ~800 judgment calls.
Probe: 72 generation + ~320 judgment calls. Total ≈ 190 generation +
~1,100 judgment calls. Embedding computed once over 55 records, vectors
cached to disk with the model hash.

## Interpretation rules (frozen)

- All gates pass → README claim upgrades to: "embedding retrieval composed
  with the governance layer fixes lexical recall gaps while retaining conflict
  detection that pure RAG lacks (measured)".
- H2 fails (E catches conflicts too) → the adversarial-benchmark framing is
  revised honestly; the corpus's conflict pairs may be lexically too easy for
  embedding retrieval to confuse — reported as-is.
- H3/H4 fail (composition loses to C) → embedding recall admits noise the
  margin rule must absorb; the failure anatomy is reported and the topic-field
  path is preferred over embeddings.
- Any gate failure does not trigger protocol edits; a follow-up experiment
  gets a new protocol.

## Threats to validity (pre-registered)

1. **Designer overlap**: the 8 probe tasks were authored by the same person as
   the protocol and the criteria — same caveat as supersedes_001, disclosed.
2. **Embedding model choice**: a multilingual model was chosen knowing the
   probe is cross-lingual — it favors F's predicted win by construction. The
   honest defense is that E's conflict-blindness prediction is
   model-independent (retrieval quality cannot supply conflict awareness).
3. **C-arm inheritance** assumes judge stability across the 14 days between
   e2e_002 and this run; the F-vs-C comparison additionally spans a provider
   interval. The mechanical selection-diff sanity anchor covers drift in
   selection; drift in judgment is disclosed as unmeasured.
4. **n = 40 + 8**, strata splits small: zero-error gates (H2, H4) carry more
   weight than rate comparisons; Wilson CIs reported throughout.
5. The real-use store (`~/.jev-work`) is never touched; this experiment runs
   entirely on the frozen v8 corpus.
