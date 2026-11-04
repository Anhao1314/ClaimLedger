# Annotation Guide — Reduced Version

**Audience:** zcode (secondary annotator). This guide contains field definitions and 3 examples only. The full judgment criteria are in the complete version, which you should not reference.

**You must not view the primary annotator's results until both of you have completed your annotations.**

## Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `pair_id` | string | yes | the pair identifier from `candidates.jsonl` |
| `edge_type` | string | yes | one of: `supports`, `contradicts`, `supersedes`, `unrelated`, `abstain` |
| `confidence` | float | yes | 0.0 to 1.0 |
| `direction` | string | only if `supersedes` | `src→dst` (src replaces dst) |
| `evidence_span` | string | no | key phrase (≤30 chars) |
| `notes` | string | no | free text |

## Edge type enum

- `supports`
- `contradicts`
- `supersedes`
- `unrelated`
- `abstain`

## Example 1

```
A: All storage must use PostgreSQL.
B: Database connections must use PostgreSQL drivers.
→ edge_type: supports
```

## Example 2

```
A: Retries must be capped at 3.
B: Retries must be capped at 5.
→ edge_type: contradicts
```

## Example 3

```
A: Deployments happen only on Tuesdays.
B: API v1 must remain unchanged.
→ edge_type: unrelated
```

## Direction

If `edge_type = supersedes`, set `direction = src→dst` (src is the newer record that replaces dst).