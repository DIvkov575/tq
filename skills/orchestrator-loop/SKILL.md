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
   work someone added since last cycle. For a task with a `project`
   assignment, prefer `expqueue project panes <project>` to find that
   project's own workspace/panes first (see "Allocating a task to a
   project" below) rather than scanning the whole fleet. Once a target
   session is picked (see step 3), deliver the task via `c11 send` +
   `c11 send-key enter` and tell that session to `expqueue pop --project
   <name>` (or plain `expqueue pop` for unassigned tasks) / `done` it.

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

## Allocating a task to a project

`expqueue project panes <name>` finds c11 workspaces whose cwd matches the
project's registered directory and lists every surface (tab) in each,
tagged with a derived `activity` (`working` / `idle` / `unknown`). It only
*discovers* candidates — it does not pick one for you:

1. Run `expqueue project panes <name> --json`. If it returns no workspaces,
   the project has no live pane right now — either spawn one (`c11
   new-workspace --cwd <project directory>` + launch an agent per the c11
   orchestration skill) or ask the user.
2. Among the returned surfaces, `activity: "idle"` is a candidate but not
   proof — always confirm with `c11 read-screen --workspace <ref> --surface
   <ref>` before delivering a task, the same way you'd verify any surface's
   state in step 3 of the main cycle. `activity: "working"` means leave it
   alone; `"unknown"` means c11 has no signal (e.g. a non-claude-code TUI
   that hasn't self-reported) — read its screen rather than trusting the tag.
3. Deliver the task into the chosen surface, then have that session run
   `expqueue pop --project <name>` so it only pulls work assigned to this
   project even if the shared queue has other projects' tasks queued too.

This only finds panes that follow c11's own "one workspace per project"
convention — a project sharing a workspace with unrelated repos (e.g. several
throwaway shells multiplexed into one "scratch" workspace) won't be found
this way; fall back to the fleet-wide `c11 tree --all` scan in step 2 of the
main cycle for those.

## Useful commands

```
expqueue list --json                     # current queue state
expqueue push "<title>" [--notes "..."] [--project demo]
expqueue pop [--project demo] --json     # FIFO pop, marks in_progress
expqueue done <id> / drop <id>
expqueue project panes demo --json       # discover demo's live c11 panes

c11 tree --workspace <ref> --no-layout --report
c11 read-screen --surface <ref>
c11 send --workspace <w> --surface <s> "<text>"
c11 send-key --workspace <w> --surface <s> enter
```
