# expqueue

A tiny file-backed experiment task queue: a Textual TUI for the human, a CLI for agents.

Storage is a single JSON file (default `~/workplace/.expqueue/queue.json`, override with `EXPQUEUE_PATH`), guarded by an flock so the TUI and CLI can read/write concurrently without corruption.

Tasks carry a status (`queued` / `in_progress` / `done` / `dropped`) and an optional project assignment. Projects are tracked separately in a registry file (default `~/workplace/.expqueue/projects.json`, override with `EXPQUEUE_PROJECTS_PATH`), each with a name, an associated local directory, and an optional GitHub repo.

## Install

```
uv sync
```

## TUI (human)

```
uv run expqueue-tui
```

The TUI has three views. Switch with `1`/`2`/`3` or cycle with `Tab`; the active view is highlighted (`*...*`) in the top bar. Auto-refreshes every 2s so it picks up changes made by an agent via the CLI.

**1 — Queue view.** Tasks grouped into visual sections (RUNNING / QUEUED / COMPLETED) instead of a flat list, plus an icon + text status column and a project column. Tasks with no project sit in the general/unassigned queue (shown as `(unassigned)`) — useful for work meant to be triaged and auto-assigned to a project later (e.g. by an orchestrator agent) rather than picked by a human up front.

Keys: `a` add, `e` edit title, `s` start, `d` done, `x` drop, `r` requeue, `p` assign to an existing project (blank clears it back to unassigned), `D` delete, `/` cycle status filter.

**2 — State view.** A per-project dashboard, not per-task: one row per known project (plus `(unassigned)`) showing task count, the most recently touched task's status, and how long ago it was touched. Use this to see at a glance which projects have been worked recently.

**3 — Config view.** Shows the current queue/projects/config file paths (from `EXPQUEUE_PATH` / `EXPQUEUE_PROJECTS_PATH` / `EXPQUEUE_CONFIG_PATH`, read-only) and the editable default project applied to new tasks added from the TUI. Press `e` to change it live.

## CLI (agent)

```
uv run expqueue push "Run ablation A" --notes "vary lr" [--project demo]
uv run expqueue list [--status queued] [--project demo] [--json]
uv run expqueue pop [--project demo] [--json]      # FIFO pop, marks in_progress
uv run expqueue start <id>
uv run expqueue done <id>
uv run expqueue drop <id>
uv run expqueue rm <id>
uv run expqueue edit <id> [--title "..."] [--notes "..."] [--project demo]
```

`pop --project <name>` scopes the FIFO pop to tasks assigned to that project, so an orchestrator managing several projects' queues can pull each project's next task independently instead of always taking the oldest task overall.

### Projects

```
uv run expqueue project add demo ~/workplace/demo [--repo me/demo] [--create-repo]
uv run expqueue project list [--json]
uv run expqueue project panes demo [--json]
```

`--create-repo` creates the GitHub repo via `gh repo create` if it doesn't already exist (requires `gh` to be authenticated). Assign a task to a project with `push --project <name>` or `edit <id> --project <name>`.

`project panes <name>` finds live [c11](https://docs.hub.amazon.dev/) workspaces/panes for a project by matching each c11 workspace's current working directory against the project's registered `directory` (exact match or subdirectory). For each matching workspace it lists every surface (tab) in it along with its derived `activity` (`working` / `idle` / `unknown`). This is discovery only — it does not decide which pane should get a task; an orchestrator reads this list (plus `read-screen` on candidate surfaces) to judge which session is actually idle before delivering a `pop --project <name>` task into it. Requires the `c11` CLI on `PATH` and a running c11 app; matching relies on c11's own "one workspace per project" convention, so a project multiplexed as one of several tabs inside an unrelated workspace (e.g. several repos crammed into a single "scratch" workspace) won't be found this way.

## Tests

```
uv run pytest
```
