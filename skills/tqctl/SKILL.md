---
name: tqctl
description: Use when you need full access to the tq per-project task queues — pushing/editing/removing tasks, and moving tasks through every state transition including releasing a task out of held. This is the unrestricted CLI; use tqctl-restricted instead if you should not be able to unhold tasks yourself.
---

# tqctl — full-access tq CLI

`tqctl` manages tasks in per-project lanes. Each registered project has its
own independent set of tasks; there's also an always-available `_unassigned`
lane for tasks with no project yet.

Every task has a status: `queued` → `running` → `completed`, plus a `held`
state reachable only from `queued`. Valid transitions:

```
queued   -> running     (start)
queued   -> held        (hold)
held     -> queued      (release)
running  -> completed    (complete)
running  -> queued       (requeue)
```

No other transition is allowed — e.g. you cannot `complete` a task that
isn't `running`, and you cannot reach `queued` from `held` via `requeue`
(only `release` does that edge).

## Commands

```
tqctl push "<title>" [--notes "<notes>"] [--project <name>]   # default project: _unassigned
tqctl list [--project <name>] [--status queued|running|held|completed] [--json]
tqctl start <id> [--project <name>]
tqctl complete <id> [--project <name>]
tqctl hold <id> [--project <name>]
tqctl release <id> [--project <name>]      # move a task OUT of held
tqctl requeue <id> [--project <name>]      # move a running task back to queued
tqctl edit <id> [--title "..."] [--notes "..."] [--project <name>]
tqctl rm <id> [--project <name>]           # delete outright, no soft-cancel state

tqctl project add <name> <directory>
tqctl project list [--json]
```

`--project` defaults to `_unassigned` on every task command. Projects must
be registered with `project add` before tasks can target them; `_unassigned`
is implicit and never appears in `project list`.

## Notes

- Storage is per-project JSON files (flock-guarded), so operations on
  different projects never contend with each other.
- `release` is the one command `tqctl-restricted` blocks. If you're an
  agent that should only be able to *place* tasks into held (e.g.
  self-pausing) but never take them back out, use that skill/binary
  instead — an orchestrator or human is expected to call `release` on
  `tqctl` (full access).
- There is no orchestrator wired up yet that automatically moves tasks
  in/out of held — that's separate, future work. Right now all state
  transitions are driven by explicit CLI calls.
