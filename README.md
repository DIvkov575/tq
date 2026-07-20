# tq

Per-project task queues with a held state: a Rust core library, a CLI with
two access levels, and a `ratatui` TUI.

Each registered project owns its own independent set of tasks (plus an
always-available `_unassigned` lane for tasks with no project yet). A task
moves through:

```
queued   -> running     (start)
queued   -> held        (hold)
held     -> queued      (release)
running  -> completed   (complete)
running  -> queued      (requeue)
```

Storage is one JSON file per project lane (default `~/.tq/projects/<name>/tasks.json`,
override the root with `TQ_HOME`), plus a project registry
(`~/.tq/projects.json`). Each file is flock-guarded so the CLI and TUI can
read/write concurrently without corruption.

## Build

```
cargo build --workspace --release
```

Produces `target/release/tqctl` and `target/release/tqctl-tui`.

## CLI — two access levels, one binary

`tqctl` is the full-access CLI. `tqctl-restricted` is the same binary
(detected by a `--restricted` flag or an argv[0] containing "restricted")
with one command blocked: `release` (moving a task out of `held`). Every
other command, including `hold`, works identically in both.

```
tqctl push "<title>" [--notes "..."] [--project <name>]   # default project: _unassigned
tqctl list [--project <name>] [--status queued|running|held|completed] [--json]
tqctl start <id> [--project <name>]
tqctl complete <id> [--project <name>]
tqctl hold <id> [--project <name>]
tqctl release <id> [--project <name>]
tqctl requeue <id> [--project <name>]
tqctl edit <id> [--title "..."] [--notes "..."] [--project <name>]
tqctl rm <id> [--project <name>]

tqctl project add <name> <directory>
tqctl project list [--json]
```

Two skills (`skills/tqctl`, `skills/tqctl-restricted`) document each mode
for agents — point an agent that must not be able to unhold tasks at the
restricted skill, and one with full control at the other.

## TUI

```
tqctl-tui
```

`ratatui`-based board: a lane bar across the top (switch projects with
`J`/`K`), four columns (QUEUED / RUNNING / HELD / COMPLETED) for the
selected lane, navigable with `h`/`j`/`k`/`l` or arrow keys. The TUI always
has full access — the held-locked restriction only applies to
`tqctl-restricted`.

Keys: `a` add task, `e` edit title, `s` start, `c` complete, `H` hold,
`r` release, `R` requeue, `d` delete, `n` register a new project, `?`
show all keybindings, `q` quit. The status bar at the bottom always shows
the keys usable right now for the focused column.

## Tests

```
cargo test --workspace
```

## Out of scope

No orchestrator is wired up to move tasks in/out of `held` automatically —
all transitions are driven by explicit CLI/TUI calls. Building that
orchestrator is separate, future work.
