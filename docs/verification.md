# Verification ledger: Memory Engine 0.2.0

## Frozen baseline

The implementation baseline is commit `3b12860e0be50472fde8808f36fe5f85639a16c7`. The first evidence workflow replays it directly from Git, not from a reconstructed snippet.

Initial baseline evidence run: https://github.com/Anhao1314/chat-distiller/actions/runs/37384832349

That run passed 101 tests on Python 3.12 and produced two identical offline benchmark runs. Its downloadable artifact includes the test output, benchmark JSON/Markdown, Python version, commit identifier, and a tracked-source archive. Artifacts have a seven-day retention period; workflows can regenerate them.

## Local candidate observations

On Python 3.13.5 in a Linux working container:

- Full suite: **137 tests passed**, including all 101 pre-existing tests and 36 new API/recovery/fault-injection tests.
- Wheel built and installed with no runtime dependencies into a new virtual environment.
- **16 installed-wheel checks passed** from outside the source checkout, including the legacy-to-v2 migration subprocess and bundled taxonomy file.
- The frozen synthetic benchmark was run twice. Both output directories were byte-identical to each other and to the frozen baseline's report.
- Two status/type projection regressions were reproduced against the original baseline: altering the note status from current to expired, or kind from decision to fact, still returned a successful query. The new regression tests failed before the fix and passed afterward.

These are correctness and packaging observations, not measured improvements in memory accuracy, hallucination rate, real-user performance, or coding task success.

## Reproduce source validation

```bash
python3 -m unittest discover -s tests -v
python3 benchmarks/evaluate.py --out /tmp/chat-distiller-benchmark-a
python3 benchmarks/evaluate.py --out /tmp/chat-distiller-benchmark-b
diff -r /tmp/chat-distiller-benchmark-a /tmp/chat-distiller-benchmark-b
```

## Reproduce installed validation

From the repository, with build tools available:

```bash
python3 -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/chat-distiller-wheels
python3 -m venv /tmp/chat-distiller-check
/tmp/chat-distiller-check/bin/python -m pip install --no-index --no-deps /tmp/chat-distiller-wheels/chat_distiller-0.2.0-py3-none-any.whl
cd /tmp
/tmp/chat-distiller-check/bin/python /absolute/path/to/chat-distiller/tools/verify_install.py
```

Use new temporary directory names on subsequent runs. The smoke script fails if it imports the checkout instead of the installed distribution. It exercises extraction, explicit identity initialization, rendering, current/historical lookup, stable-ID inspection, byte-bounded recovery, deterministic rerender, lint, legacy migration, note-status corruption, and index corruption. Semantic cards are explicitly handwritten synthetic examples; no model API or host-compaction event is exercised.

## Continuous evidence

`.github/workflows/tests.yml` runs the full source suite and installed-wheel smoke checks on Python 3.9 and 3.12. `.github/workflows/evidence.yml` replays the frozen baseline, executes candidate tests, compares benchmark outputs with the baseline, tests the installed wheel, and uploads inspectable evidence. CI definitions are not themselves a success claim: inspect the completed workflow run for the specific commit.

The original 40-session / 40-card / 24-query fixture remains a small development regression set. It is unchanged and still does not establish automatic-distillation quality, expired-target recall, or final agent-answer correctness.

## Documentation and onboarding verification

The documentation refresh builds on merged source `d0032e90b9db378c5ec446e698713f2d5daa2190`
(tree `27429a1332f7340c17ebdc1d703976286f8a6235`). It does not change engine code, source
schema, runtime dependencies, or frozen benchmark fixtures.

Local verification in a clean Linux / Python 3.13.5 environment:

- **147 source tests passed**: the prior 137 plus 10 documentation-contract regressions.
- The exact marked Bash and Python examples in both READMEs match and execute with the
  installed CLI. SDK imports are checked from outside the source checkout.
- The ingestion example extracts synthetic JSONL and lints the rendered demo vault.
- Four recovery cases are checked: current, historical, no match, and budget exhausted.
  The generated [JSON receipt](../examples/recovery/expected.json) and
- Local Markdown file targets and fragments are checked. External HTTP destinations are
  counted but not fetched; this is not an external-link availability audit.
- Two benchmark runs remain byte-identical to each other and the committed baseline.

Run `python tools/verify_docs.py` with the installed environment activated. Demo writes
use new temporary directories, not an existing user vault. The optional `--write-demo`
flag regenerates only the repository's demo JSON/SVG after execution; ordinary verification
never updates expected artifacts. These are synthetic CLI observations, not a live model,
native-host compaction test, or measured improvement in agent task success.

Both CI workflows also run these installed documentation checks. The evidence workflow
retains `docs-smoke.json` beside the source-test, benchmark, and wheel-install logs.

## Knowledge Wiki 0.3.0

The subsequent compiler delivery has its own [research and failure-testing ledger](wiki-verification.md).
The original retrieval benchmark remains frozen; the new results concern structural compilation and lifecycle behavior.
