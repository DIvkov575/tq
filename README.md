# tq

A tiny file-backed task queue tightly coupled to a persistent c11
orchestrator agent: a Textual TUI for the human (informational only), a CLI
for the orchestrator and for manual/debug use.

Storage is a single JSON file (default `~/workplace/.tq/queue.json`,
override with `TQ_PATH`), guarded by an flock so the TUI and CLI can
read/write concurrently without corruption.

Tasks carry a status (`queued` / `in_progress` / `done` / `dropped`) and an
optional project assignment. Projects are tracked separately in a registry
file (default `~/workplace/.tq/projects.json`, override with
`TQ_PROJECTS_PATH`), each with a name, an associated local directory, an
optional GitHub repo, and — once the orchestrator has delivered work to it —
a bound c11 pane (`workspace_ref` / `surface_ref`).

## Install

```
uv sync
```

## TUI (human, informational only)

```
uv run tq-tui
```

The TUI is not a control surface — the orchestrator is. It exists to
visualize the queue and give a trace of what the orchestrator knows.

- **Queue view** (default, `1`): tasks grouped into RUNNING / QUEUED /
  COMPLETED sections. An unassigned queued task (project column shows
  `(unassigned)`) is the orchestrator's triage signal — it hasn't routed it
  to a project yet. The bottom panel shows orchestrator health (alive/not
  running, idle/working) and its 5 most recent activity log entries.
- **Projects view** (`2`): every registered project — name, directory,
  repo (blank = local-only), bound pane (`workspace_ref`/`surface_ref`, or
  `(unbound)`), and that pane's live status (`idle` / `working` / `unknown`
  / `gone`).

Auto-refreshes every 2s so it picks up changes made by the orchestrator or
CLI. Keys: `1`/`2` switch view, `Tab` cycle view, `a` add, `e` edit title,
`d` done, `x` drop, `s` start, `r` requeue, `p` assign to an existing project,
`D` delete, `/` cycle status filter, `q` quit.

## CLI (orchestrator + manual use)

```
uv run tq push "Run ablation A" --notes "vary lr" [--project demo]
uv run tq list [--status queued] [--project demo] [--json]
uv run tq pop [--project demo] [--json]      # manual FIFO pop, marks in_progress (debug only — the orchestrator pushes, it doesn't pop)
uv run tq start <id>
uv run tq done <id>
uv run tq drop <id>
uv run tq rm <id>
uv run tq edit <id> [--title "..."] [--notes "..."] [--project demo]
```

### Projects

```
uv run tq project add demo ~/workplace/demo [--repo me/demo] [--create-repo] [--init-dir]
uv run tq project list [--json]
uv run tq project bind demo /tmp/prompt.md
```

`--create-repo` creates the GitHub repo via `gh repo create` if it doesn't
already exist (requires `gh` to be authenticated). `--init-dir` creates the
local directory (and runs `git init` inside it) if it doesn't already exist.

`project bind <name> <prompt-file>` creates a new pane for `<name>` inside
the shared c11 workspace and launches an agent into it with the prompt
file's contents as its first task. This is normally called by the
orchestrator itself the first time it needs to deliver work to a project
with no pane yet — see the `tq-orchestrator` skill.

### Orchestrator

```
uv run tq orchestrator log "<message>"
uv run tq orchestrator recent [--limit N] [--json]
uv run tq orchestrator claim <owner> [--json]
uv run tq orchestrator release <owner>
uv run tq orchestrator ensure <prompt-file>
```

The orchestrator is a **persistent** c11 agent — one pane, nudged by a cron
cadence (e.g. `/loop 5m`) rather than respawned each cycle, so its context
accumulates across cycles. `tq orchestrator ensure <prompt-file>` checks
whether the recorded orchestrator pane (`Config.orchestrator_workspace_ref`
/ `orchestrator_surface_ref`) is still alive, and spawns a fresh one into the
shared workspace (`Config.shared_workspace_ref`, created on first use) if
not. Call this before nudging, and on tq TUI startup.

`claim <owner>` / `release <owner>` implement a short-lived (60s) cooperative
mutex purely around the "ensure orchestrator is alive, spawn if not"
sequence — not a whole cycle — so two processes racing to notice a dead
orchestrator don't both spawn a replacement.

The orchestrator's own behavior (which project a task belongs to, when to
bind a new pane vs. deliver into an existing one, driving obvious in-pane
decisions, what to escalate) is documented in the `tq-orchestrator` skill,
not in this CLI.

## Tests

```
uv run pytest
```
