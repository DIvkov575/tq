# expqueue

A tiny file-backed experiment task queue: a Textual TUI for the human, a CLI for agents.

Storage is a single JSON file (default `~/workplace/.expqueue/queue.json`, override with `EXPQUEUE_PATH`), guarded by an flock so the TUI and CLI can read/write concurrently without corruption.

## Install

```
uv sync
```

## TUI (human)

```
uv run expqueue-tui
```

Keys: `a` add, `e` edit title, `s` start, `d` done, `x` drop, `r` requeue, `D` delete, `/` cycle status filter, `q` quit. Auto-refreshes every 2s so it picks up changes made by an agent via the CLI.

## CLI (agent)

```
uv run expqueue push "Run ablation A" --notes "vary lr"
uv run expqueue list [--status queued] [--json]
uv run expqueue pop [--json]      # FIFO pop, marks in_progress
uv run expqueue start <id>
uv run expqueue done <id>
uv run expqueue drop <id>
uv run expqueue rm <id>
```
