---
name: tqctl-restricted
description: Use when you need to work with the tq per-project task queues but must NOT be able to move a task out of held yourself — e.g. an agent that can pause its own work but shouldn't be able to unpause work someone else held. Every command works except `release`; use the tqctl skill instead if you have (or should have) full access.
---

# tqctl-restricted — held-locked tq CLI

Same task model as `tqctl` (see that skill for the full state machine), but
invoked as `tqctl-restricted` — a binary that behaves identically to
`tqctl` except that `release` (moving a task from `held` back to `queued`)
always fails:

```
$ tqctl-restricted release <id>
error: operation not permitted in restricted mode: release (moving a task out of held)
```

Everything else works normally, including `hold` — you can still put a
task on hold yourself, you just can't take it back off hold. There is no
way around this restriction from this binary: `requeue` only applies to
`running` tasks, so a `held` task cannot reach `queued` through it either.

## Commands (identical to tqctl, minus release)

```
tqctl-restricted push "<title>" [--notes "<notes>"] [--project <name>]
tqctl-restricted list [--project <name>] [--status queued|running|held|completed] [--json]
tqctl-restricted start <id> [--project <name>]
tqctl-restricted complete <id> [--project <name>]
tqctl-restricted hold <id> [--project <name>]
tqctl-restricted requeue <id> [--project <name>]
tqctl-restricted edit <id> [--title "..."] [--notes "..."] [--project <name>]
tqctl-restricted rm <id> [--project <name>]

tqctl-restricted project add <name> <directory>
tqctl-restricted project list [--json]
```

## When you hit a held task you need released

If your work needs a task un-held and you're using this restricted CLI,
that's by design — escalate to whoever has `tqctl` (full access): a human,
or an orchestrator process. Don't attempt to work around the restriction
(e.g. deleting and re-pushing the task) — that erases the task's history
instead of actually resolving why it was held.
