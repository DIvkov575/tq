---
name: orchestrator-loop
description: Use when polling/driving a fleet of c11 sessions against the expqueue task queue — checking for new queued tasks, checking c11 panes for sessions that finished or are waiting on input, driving straightforward continuations, and escalating hard decisions to the user. Also covers what to do when a session finishes all its work.
---

# Orchestrator Loop

Drives a recurring orchestration cycle across two systems: the `expqueue` task
queue (see the `expqueue` CLI — `expqueue list/push/pop/done/drop`) and a c11
workspace full of live agent sessions (terminals in panes/surfaces).

## Cycle

Each time this runs (typically on a `/loop` cron cadence):

1. **Check expqueue**: `expqueue list --json`. Any `queued` items are new
   work someone added since last cycle — decide which idle/finished session
   should pick each one up (see step 3), then deliver it via `c11 send` +
   `c11 send-key enter` and tell that session to `expqueue pop`/`done` it.

2. **Poll the c11 workplace workspace**: `c11 tree --workspace <ref> --no-layout --report`
   to enumerate panes/surfaces, then `c11 read-screen --surface <ref>` on each
   active `claude-code`/`codex` surface to see its tail output.

3. **Classify each surface's state** and act:
   - **Actively running** (mid tool-call, spinner, no prompt showing) — leave alone.
   - **Waiting on a simple/mechanical continuation** ("want me to proceed?",
     "should I start X?", straightforward yes/no with an obvious answer) —
     drive it yourself: `c11 send --workspace <w> --surface <s> "<instruction>"`
     then `c11 send-key --workspace <w> --surface <s> enter`.
   - **Finished all its work / fully idle with nothing left to do** — **never
     leave it dangling.** Either:
     a. Give it a new task right now — pull the next `queued` item from
        expqueue (or push one yourself if you know of follow-up work implied
        by what it just finished) and deliver it, or
     b. If there's no obvious next task, ask the user what this session
        should do next — don't just report "it's done" and move on.
   - **Waiting on a genuinely hard/ambiguous decision** (architecture choice,
     which of several options to pursue, anything with real consequences or
     unclear intent) — do not decide for the user. Summarize the decision
     and ping them.

4. **Report back tersely**: what's newly queued, what you drove, what you
   escalated. Don't re-list surfaces that are unchanged and still running.

## Why "never leave it idle" matters

An idle agent session is wasted capacity sitting in a live pane. The user
corrected this explicitly after a session (cozempic) finished a full task
list and merged its PR, and the orchestrator just reported "done" without
feeding it new work or asking what's next. Treat every finished session as
requiring one of: new task, or an explicit question to the user — every cycle,
not just the first time it goes idle.

## Useful commands

```
expqueue list --json          # current queue state
expqueue push "<title>" [--notes "..."]
expqueue pop --json           # FIFO pop, marks in_progress
expqueue done <id> / drop <id>

c11 tree --workspace <ref> --no-layout --report
c11 read-screen --surface <ref>
c11 send --workspace <w> --surface <s> "<text>"
c11 send-key --workspace <w> --surface <s> enter
```
