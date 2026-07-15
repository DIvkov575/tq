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

Keys: `a` add, `e` edit title, `s` start, `d` done, `x` drop, `r` requeue, `p` assign project, `D` delete, `/` cycle status filter, `q` quit. Auto-refreshes every 2s so it picks up changes made by an agent via the CLI. The table shows an icon + text status column and a project column for every task.

## CLI (agent)

```
uv run expqueue push "Run ablation A" --notes "vary lr" [--project demo]
uv run expqueue list [--status queued] [--project demo] [--json]
uv run expqueue pop [--json]      # FIFO pop, marks in_progress
uv run expqueue start <id>
uv run expqueue done <id>
uv run expqueue drop <id>
uv run expqueue rm <id>
uv run expqueue edit <id> [--title "..."] [--notes "..."] [--project demo]
```

### Projects

```
uv run expqueue project add demo ~/workplace/demo [--repo me/demo] [--create-repo]
uv run expqueue project list [--json]
```

`--create-repo` creates the GitHub repo via `gh repo create` if it doesn't already exist (requires `gh` to be authenticated). Assign a task to a project with `push --project <name>` or `edit <id> --project <name>`.

## Tests

```
uv run pytest
```
