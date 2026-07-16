---
name: tqctl
description: Use when you need full access to the tq per-project task queues — pushing/editing/removing tasks, moving tasks through every state transition including releasing a task out of held, or checking whether the current session's directory has a registered tq queue and what's in it. This is the unrestricted CLI; use tqctl-restricted instead if you should not be able to unhold tasks yourself.
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

## Checking if the current session's directory has a queue

If you want to know whether the project you're working in right now has a
tq queue, match your session's current working directory against the
`directory` field of `tqctl project list --json` — exact match, not a
prefix/subdirectory match.

```
tqctl project list --json
```

If your cwd matches a registered project's `directory`, that project's
name is what you pass as `--project` everywhere else:

```
tqctl list --project <name> --status queued
```

Only look at `queued` tasks this way — `running`/`held`/`completed` aren't
part of this check. If your cwd doesn't match any registered project,
there's no queue for this directory; don't fall back to `_unassigned`,
that lane isn't tied to any specific directory.

**Never push a task as part of this check.** Only look — `push`/`edit`/
`rm`/state transitions happen only when the user explicitly asks for them.

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
