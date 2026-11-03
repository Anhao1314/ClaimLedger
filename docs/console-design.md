# Console design — v2, user-first

Design record for the next console iteration. The previous round added features
(three-pane layout, agents, history). This round starts from the question:
**what does a user come here to do, and what stops them?**

**Status:** implemented in `jev_first/web_page.py` and `jev_first/web.py`;
the screenshots in the README are from this version.

---

## 1. Who the user is

One developer, working in a terminal with an AI coding agent. The console is
not their main window — they open it a few times a day, for under a minute.

## 2. The five jobs

| # | Job | Frequency |
| --- | --- | --- |
| 1 | "Ask what applies to this task before I start" | several times a day |
| 2 | "Record a decision I just settled" | several times a day |
| 3 | "Check whether the agent's verdict made sense" | once a day |
| 4 | "Is the system getting more reliable?" | weekly |
| 5 | "What did it decide yesterday?" | occasionally |

Everything in the UI must serve one of these. If it serves none, it is removed.

## 3. What currently blocks the user

Evidence is from real use, including two failed automation attempts that
reproduced the same confusion a human would hit.

| # | Problem | Consequence |
| --- | --- | --- |
| 1 | Two text boxes with unclear roles ("record a decision…" in the sidebar, "Describe a task…" at the bottom) | the user types the task into the record box; nothing happens |
| 2 | First run is a dead end: empty store, no records, no guidance | the user does not know what to type, or that records must exist first |
| 3 | The composer promises a verdict, but a fresh store yields "all review" | first-run experience feels broken |
| 4 | Outcome buttons appear on every record, but calibration scores `admit` only | most clicks do nothing measurable, and nothing says so |
| 5 | The brief — the actual product — cannot be copied in one action | terminal users copy by hand, every time |
| 6 | Clicking a record does nothing; per-record judgment history exists in the API but not in the UI | "why was this excluded last time?" is unanswerable |
| 7 | Calibration is a 10-pixel line in the sidebar | job 4 cannot be done |
| 8 | Agents section occupies prime sidebar space for a solo user | cognitive load with no payoff |

## 4. Design principles

1. **One input, one role.** The composer does tasks. Recording is a deliberate
   action, not a permanent second box.
2. **Progressive disclosure.** First run teaches the loop; agents and settings
   collapse once the user knows the way.
3. **The brief is the product.** It gets a copy action and the visual weight.
4. **Say what counts.** Every outcome click states whether it moves calibration.

## 5. Information architecture

```
Sidebar (240px)                 Canvas                    Overlay
──────────────                  ──────                    ───────
Brand                           Topbar: task + actions      Calibration
+ New task                       └ Copy brief               (slide-over)
                                 Brief card
History (task, time,             Records card
  conflict count)                 └ click → record drawer
                                 Composer (fixed bottom)
──────────────
Footer: chains · Settings ▸
```

Removed from the sidebar: the permanent record input, the agents list, the
calibration mini-panel. All three survive elsewhere: record via the topbar
action, agents inside Settings, calibration as a slide-over.

## 6. Screens

### 6.1 First run (zero records)

```
┌──────────────┬─────────────────────────────────────┐
│ ClaimLedger  │  Start in three steps               │
│ + New task   │                                     │
│              │  1  Record a decision               │
│ HISTORY      │     [ Add one ]  [ Load 5 examples ]│
│ (empty)      │                                     │
│              │  2  Ask what applies                │
│              │     (the composer below)            │
│              │                                     │
│              │  3  Review the verdict              │
│              │     upheld / overturned             │
│──────────────│                                     │
│ ●0 ●0 ●0     │  ┌───────────────────────────────┐  │
│ Settings ▸   │  │ Describe a task…          ↑   │  │
└──────────────┴─────────────────────────────────────┘
```

The "Load 5 examples" button seeds non-conflicting decisions so step 2 can
produce an actual `admit` verdict on the first try.

### 6.2 Daily judgment

```
┌──────────────┬─────────────────────────────────────┐
│ ClaimLedger  │ Write a storage adapter…   [Copy]   │
│ + New task   │─────────────────────────────────────│
│              │ Brief                  [Copy brief] │
│ HISTORY      │ ✓ Active constraints (1)            │
│ ▸ task A     │   · All storage must use PostgreSQL │
│ ▸ task B 1⟂  │ ⚠ Needs human review (2)            │
│ ▸ task C     │   · banned [conflict]               │
│              │ ⛔ Unresolved conflicts               │
│              │   · banned ⟂ all-PostgreSQL         │
│              │                                     │
│              │ Records        scoreable: 2 of 3    │
│              │ · PostgreSQL  [review] [upheld]…    │
│              │   tooltip: recorded; scores admit only
│──────────────│                                     │
│ ●6 ●3 ●1     │  ┌───────────────────────────────┐  │
│ Settings ▸   │  │ Describe a task…          ↑   │  │
└──────────────┴─────────────────────────────────────┘
```

Outcome buttons on non-`admit` records are visually ghosted and carry a
tooltip. The scoreable count appears in the Records header.

### 6.3 Record drawer (click a record)

```
┌───────────────────────────────┐
│ All storage must use PostgreSQL│
│ author: researcher-01          │
│ ─────────────────────────────  │
│ 11-03 06:27  review  0.43      │
│ 11-02 18:12  admit   0.91      │
│ 11-01 09:40  admit   0.88      │
│ [Copy record id]               │
└───────────────────────────────┘
```

Backed by a new `GET /api/record-history?record_id=…` (the audit view already
computes this).

### 6.4 Calibration slide-over

```
┌───────────────────────────────┐
│ Calibration              [×]  │
│ 12 scored · upheld 0.83        │
│ Brier 0.11                     │
│                                │
│ p(admit) bucket  n   upheld    │
│ [0.6,0.7)        3   0.67 ██   │
│ [0.7,0.8)        5   0.80 ███  │
│ [0.8,0.9)        4   1.00 ████ │
│                                │
│ by author       n   upheld     │
│ researcher-01   6   0.83       │
│ eason           6   0.83       │
│ [Export JSON]                  │
└───────────────────────────────┘
```

## 7. Keyboard and small details

| Key | Action |
| --- | --- |
| `/` | focus the composer |
| `Esc` | clear the composer, close overlays |
| `⌘↵` | judge |
| `c` | copy brief (when the composer is not focused) |

- New task clears the canvas and focuses the composer.
- Selecting a history item re-renders that sealed judgment, outcomes included.
- The topbar copy copies the brief text exactly as the agent would receive it.

## 8. Explicitly not in this round

- Search across records (history is short; add when it hurts)
- Multi-agent switching in the main flow (move into Settings)
- Themes beyond light/dark
- Charts for calibration beyond the bucket bars
- Any new backend concept: this round changes only presentation and two
  endpoints (`/api/record-history`, `/api/seed-examples`)

## 9. Acceptance criteria (user-level)

1. A new user reaches a rendered brief in under 60 seconds without reading docs.
2. No screen contains two text inputs with ambiguous roles.
3. Every outcome click states whether it moves the calibration score.
4. The brief is copyable in one click or keystroke.
5. Calibration is readable at a glance without squinting.
6. The agents registry is still reachable but not in the primary flow.