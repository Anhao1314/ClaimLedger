# Annotation Guide — Full Version

**Audience:** primary annotator (human). This guide contains the complete judgment criteria, examples, and edge cases.

**You must not view the other annotator's results until both of you have completed your annotations.**

## What you are annotating

Given a pair of records (two standalone statements from a project's decision log), classify their relationship into exactly one of five types.

## The five types

### `supports`

One record provides evidence, refinement, elaboration, or repetition for the other. If you follow one, the other is reinforced or at least not contradicted.

**Mark `supports` when:**
- One is a specific instance or application of the other
- One explains why the other exists
- Both state the same constraint using different wording
- One adds operational detail to a high-level rule without changing it

**Do NOT mark `supports` when:**
- The records are about different systems or concerns (that's `unrelated`)
- One replaces the other (that's `supersedes`)
- Following one makes the other impossible (that's `contradicts`)

**Examples:**

| Record A | Record B | Type | Why |
|---|---|---|---|
| All storage must use PostgreSQL. | Database connections must use PostgreSQL drivers. | supports | B is an operational detail of A |
| Retries must be capped at 3. | Exponential backoff must not exceed 3 attempts. | supports | Both enforce the same cap |
| The default locale is en-US. | User-facing strings default to en-US unless overridden. | supports | B refines A |

### `contradicts`

Following both records is impossible. One record forbids what the other requires, or they specify incompatible values for the same thing.

**Mark `contradicts` when:**
- One says "must do X" and the other says "must not do X"
- They specify different numeric limits for the same thing ("cap at 3" vs "cap at 5")
- One applies to all services and the other bans it for a specific service, making compliance impossible
- They require mutually exclusive states of the same resource

**Do NOT mark `contradicts` when:**
- The records are about different services or scopes and can both be followed in their own scope
- One is more restrictive but doesn't make the other impossible
- The incompatibility is temporal but both were true at different times (that might be `supersedes`)

**Examples:**

| Record A | Record B | Type | Why |
|---|---|---|---|
| All storage must use PostgreSQL. | PostgreSQL is banned for the analytics service. | contradicts | A applies to all services including analytics; B bans it there |
| Retries must be capped at 3. | Retries must be capped at 5. | contradicts | Incompatible limits |
| The console must not add any new panels. | The console must add a proposals panel. | contradicts | Direct conflict on the same action |

### `supersedes`

One record replaces the other due to a decision change, version update, or time passage. The superseded record is no longer intended to be followed.

**Mark `supersedes` when:**
- One is explicitly a newer version of the other
- One reverses a previous decision
- One narrows or broadens the scope in a way that makes the old rule moot
- One is marked as deprecated/replaced in the text

**Requires direction:** you must indicate which record supersedes which. Convention: `src` is the NEW record, `dst` is the OLD record (src supersedes dst).

**Do NOT mark `supersedes` when:**
- The two records complement each other (that's `supports`)
- The two records contradict each other but neither is clearly "newer" (that's `contradicts` — a human decides which wins)
- The replacement is implied but not stated in the text

**Examples:**

| Record A (new) | Record B (old) | Type | Why |
|---|---|---|---|
| Use PostgreSQL 16. | Use PostgreSQL 15. | supersedes | Version update |
| Logging is no longer required for debug endpoints. | All endpoints must log requests. | supersedes | Policy reversal |

### `unrelated`

The two records talk about different aspects, systems, or concerns. Following one has no bearing on the other.

**Mark `unrelated` when:**
- They are about different subsystems, tools, or teams
- They operate at different abstraction levels with no shared constraint
- One is about infrastructure, the other about UI, with no overlap

**Do NOT mark `unrelated` when:**
- They share a common resource or constraint, even if the wording differs
- One could affect the other's implementation

**Examples:**

| Record A | Record B | Type | Why |
|---|---|---|---|
| Deployments happen only on Tuesdays. | API v1 must remain unchanged. | unrelated | Different concerns |
| The default locale is en-US. | Health checks must not depend on the database. | unrelated | Different subsystems |

### `abstain`

The relationship cannot be determined from the available context. Use this sparingly — a high abstain rate means the ontology definitions are unclear.

**Mark `abstain` when:**
- The records are too short or generic to classify
- The relationship requires domain knowledge you don't have
- The records seem related but you can't determine which type

## Confidence

Rate your confidence in each classification from 0.0 to 1.0:

| Score | Meaning |
|---|---|
| 0.9–1.0 | Certain; the classification is unambiguous |
| 0.7–0.9 | Confident; minor ambiguity but the type is clear |
| 0.5–0.7 | Uncertain; could plausibly be another type |
| < 0.5 | Should probably be `abstain` |

## Common pitfalls

1. **Don't confuse `contradicts` with scope differences.** Two rules about the same topic but different services can both be followed. Only mark `contradicts` if following both is impossible in the same scope.
2. **Don't confuse `supersedes` with `contradicts`.** `supersedes` requires a temporal/version semantic — one explicitly replaces the other. If they just conflict, it's `contradicts`.
3. **Don't mark `supports` for records that merely coexist.** They must actually reinforce or elaborate each other.
4. **When in doubt, `abstain`.** A wrong label is worse than an abstention.

## The value is a number of days

When a record says "retained for N days" or similar, treat the numeric value as part of the record. Two records with different values for the same metric are `contradicts`, not `supports`.