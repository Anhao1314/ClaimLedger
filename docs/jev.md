# Jev adapter (optional, off by default)

[TypeSafe System One](https://docs.typesafe.ai/introduction) models take an
unstructured `state` and return **typed, calibrated decisions**: a choice from a
fixed set, a score against ordered levels, or a yes/no probability. This
repository ships a zero-dependency client for it.

**It is not wired into retrieval.** It is a probe and a building block, for the
reason recorded in [DECISION.md](DECISION.md): the next question is empirical,
not architectural.

---

## 1. Configuration

The client reads two environment variables and never writes them anywhere:

| Variable | Meaning |
|---|---|
| `TYPESAFE_API_KEY` | Required. Without it, `configured()` is `False` and every call raises `JevError`. |
| `TYPESAFE_MODEL` | Optional. Defaults to `jev-latest`. |

Keep the credential **outside the repository**. One way:

```bash
mkdir -p ~/.config/claimledger && chmod 700 ~/.config/claimledger
printf "export TYPESAFE_API_KEY='%s'\n" "$YOUR_KEY" > ~/.config/claimledger/jev.env
chmod 600 ~/.config/claimledger/jev.env
```

Then `source ~/.config/claimledger/jev.env` in the shell that runs the probe.
`.env`, `.env.*` and `*.env` are gitignored as a second fence.

## 2. Contract

```
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <key>

{"state": "...", "model": "jev-latest",
 "questions": {"id": {"type": "choice" | "score" | "noul",
                      "instructions": "...",
                      "criteria": {...} or [...]}}}

→ {"model": "jev-1.14.0",
   "answers": {"id": {"type": ..., "choice"/"score"/"noul": ...,
                      "confidence": ..., "probabilities": {...}}},
   "usage": {"input_tokens": ..., "output_tokens": ...}}
```

`noul` returns a probability in 0–1; `choice` returns the label plus a full
probability map; `score` returns an index plus a `legend`.

## 3. Measured behaviour (2026-11-02)

Probe: five claim pairs with known relations, including the pair a lexical
detector cannot separate (`PostgreSQL is banned` vs `Use PostgreSQL`).

| Case | Expected | Observed | Confidence | p(contradiction) |
|---|---|---|---|---|
| C1 | contradiction | contradiction | 0.97 | 0.98 |
| C2 | complementary | complementary | 0.64 | 0.14 |
| C3 | unrelated | unrelated | 1.00 | 0.00 |
| C4 | **contradiction** | **contradiction** | **1.00** | **1.00** |
| C5 | complementary | complementary | 1.00 | 0.00 |

**Agreement: 5/5.** C4 is the case `find_conflicts` cannot see, because token
overlap is high while the meaning is opposite. Two independent runs gave the
same labels; C2's confidence moved (0.64 → 0.49) while its label did not.

### Latency: measured, not advertised

TypeSafe documents 70–500 ms. From this machine the observed end-to-end time was
**1.6–4.4 s** across ten calls, warm or cold:

```
C1 2268ms  C2 2629ms  C3 3262ms  C4 1955ms  C5 4420ms   (run 1)
C1 3538ms  C2 2075ms  C3 1624ms  C4 2563ms  C5 2347ms   (run 2)
```

**This decides the architecture.** At 2–4 s, Jev cannot sit in an interactive
retrieval path. It belongs at write time (one call per recorded claim) or in
offline batch work, never per read.

## 4. Privacy boundary

Calling the adapter sends the `state` string to `api.typesafe.ai`. The module
therefore requires `consent=True` on every call, and the README's "zero network
calls" claim is qualified to "by default". Nothing in the default path
(`claim record`, `claim brief`, `claim search`, MCP tools) calls this module.

Do not pass a whole ledger. Pass the minimum text a single decision needs.

## 5. Usage

```python
from chat_distiller import jev

if jev.configured():
    response = jev.ask(
        "Statement A: PostgreSQL is banned here.\nStatement B: Use PostgreSQL.",
        {"relation": jev.choice(
            "How do A and B relate",
            {"contradiction": "Both cannot hold",
             "complementary": "Both can hold",
             "unrelated": "They do not constrain each other"})},
        consent=True,
    )
    answer = jev.answer(response, "relation")
    print(answer["choice"], answer["confidence"])
```

Probe script:

```bash
source ~/.config/claimledger/jev.env
python scripts/jev_probe.py
```

Exit code is `0` only when all five labelled cases agree.

## 6. What this is not

- It is not a truth oracle. It returns calibrated judgements about the text you
  give it; TypeSafe states the model "does not establish content truth".
- It is not connected to the claim store. No claim is written, superseded, or
  hidden by this module.
- It is not a replacement for `find_conflicts`. The lexical detector remains the
  default; Jev is a candidate for a *proposal* layer that a human or a
  deterministic policy still has to accept.

[Back to README](../README.md)