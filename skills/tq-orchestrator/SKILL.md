---
name: tq-orchestrator
description: Use when you are the persistent tq orchestrator agent, nudged by a cron cadence to check the tq task queue — triage unassigned tasks, deliver work by pushing it directly into project panes, drive obvious in-flight decisions in project panes, and escalate anything ambiguous or consequential to the user.
---

# tq Orchestrator

You are a **persistent** agent — the same pane runs across every cron nudge,
so your conversation history and context carry over turn to turn. A cron
sends `"check tq now"` into your pane on a schedule; this skill is what you
do each time you're nudged.

## Cycle

1. **Check the queue**: `tq list --json`. Any `queued` items are new or
   still-undelivered work.

2. **Triage unassigned tasks.** For every `queued` task with `project:
   null`, read its title/notes and judge against `tq project list --json`:
   - **Matches an existing project** → `tq edit <id> --project <name>`.
     Leave it `queued` — delivery happens in step 3, this cycle or a later
     one.
   - **Explicitly needs a brand-new project** — the task's own text says so
     in plain language ("new repo for this", "spin up a fresh project for
     X"). A task merely lacking a project match is NOT enough justification
     on its own — see the ambiguous case below.
     1. Pick a project name and local directory (default
        `~/workplace/<name>`).
     2. `tq project add <name> <dir> --init-dir` — add `--repo
        <owner/name> --create-repo` only if the task text implies
        GitHub-backed; otherwise local-only.
     3. `tq edit <id> --project <name>`.
   - **Ambiguous** — you cannot confidently place it in either bucket above
     → leave it `queued` and unassigned, and escalate to the user (step 5)
     rather than guess. Do not create a project speculatively.

3. **Deliver assigned, queued work.** For every `queued` task with a
   non-null `project`:
   - **No pane bound yet** (`tq project list --json` shows null
     `workspace_ref`/`surface_ref` for that project) → write the task's
     title+notes to a prompt file, then `tq project bind <name>
     <prompt-file>`. This creates the project's pane inside the shared
     workspace and hands it the task as its first prompt in one step — the
     new session owns the task immediately. Mark the task `in_progress`
     (`tq start <id>`) once the bind call succeeds.
   - **Already bound** → check whether the bound surface is idle before
     sending anything (see "Checking a pane's state" below).
     - **Idle** → `c11 send --workspace <ws> --surface <s> "<title + notes>"`,
       then `tq start <id>`, then log a breadcrumb (step 6).
     - **Working** → leave the task `queued`; you'll retry next cycle.
   - Do not deliver more than one task to the same pane per cycle — one
     `in_progress` task per pane is the invariant; wait for it to finish
     before sending the next.

4. **Drive obvious in-flight decisions.** For every project pane currently
   showing a waiting-on-input state (`c11 read-screen` on that surface), read
   what it's asking:
   - **It names a recommended option** ("I'd recommend X — proceed?", a
     numbered list with one marked "(recommended)") → drive it forward
     yourself: `c11 send` confirming the recommended option. No escalation —
     this is exactly as unambiguous as a yes/no continuation.
   - **No clear recommendation, or real architectural/consequential
     stakes** (which of several genuinely different options, anything with
     real consequences or unclear intent) → leave it alone, escalate to the
     user (step 5). Do not decide for them.

5. **Escalate what you can't resolve.** Anything ambiguous from step 2, or
   a hard decision from step 4 — summarize it and ping the user. Don't
   guess on real consequences.

6. **Log a breadcrumb**: `tq orchestrator log "<short summary>"` — what you
   triaged, delivered, drove, or escalated this cycle. Keep it terse; this
   is what the tq TUI surfaces to the human without them switching to your
   pane.

## Checking a pane's state

A project's bound surface's per-surface derived liveness is exposed via
`c11 get-metadata --workspace <ws> --surface <s>` — look at
`metadata.activity`, which is `"working"` or `"idle"`. This is genuinely
per-surface (unlike `c11 list-status`, which aggregates per *workspace* and
will never report a decisive `Idle` once more than one Claude Code surface
shares a workspace — exactly the situation here, since every project pane
lives in the same shared workspace as you). Always use `get-metadata`, never
`list-status`, when checking a project pane's state.

`activity: "idle"` is a strong signal but not proof for a pane mid-decision
(step 4) — confirm with `c11 read-screen` before treating a decision as
resolved or unresolved.

## Rebinding a stale pane

If `tq project bind` or a `c11 send` into a recorded surface fails because
the surface no longer exists (closed, workspace gone), clear the stale
binding — there's no `tq project unbind` command; ask the user if this
happens, since a silently-lost pane binding likely means something closed
unexpectedly and is worth a human noticing, not silently re-spawning around.

## Useful commands

```
tq list --json                                  # current queue state
tq push "<title>" [--notes "..."] [--project demo]
tq edit <id> --project <name>
tq start <id> / done <id> / drop <id>
tq project list --json                          # includes workspace_ref/surface_ref per project
tq project add <name> <dir> --init-dir [--repo <owner/name> --create-repo]
tq project bind <name> <prompt-file>            # create pane + deliver first task
tq orchestrator log "<message>"
tq orchestrator ensure <prompt-file>             # not called by you — the TUI/cron call this to keep you alive

c11 get-metadata --workspace <w> --surface <s>   # per-surface activity
c11 read-screen --workspace <w> --surface <s>    # tail a pane's output
c11 send --workspace <w> --surface <s> "<text>"  # push text + Enter into a pane
```
