# Orchestrator-driven task triage + TUI simplification

## Context

expqueue is a file-backed task queue (JSON, flock-guarded) with a Textual TUI
for humans and a CLI for agents. Tasks optionally carry a `project`
assignment; a separate project registry (`projects.json`) tracks each
project's name, local directory, and optional GitHub repo. A prior change
added `expqueue project panes <name>`, which discovers live c11
workspaces/panes for a project by matching workspace cwd against the
project's registered directory.

The `orchestrator-loop` skill drives a recurring cycle: poll expqueue for new
tasks, poll c11 panes for idle/waiting sessions, deliver work, escalate hard
decisions.

Goal: push all new tasks into the single central queue, tagged only by
whatever plain-language context the human writes into the title/notes.
The orchestrator itself performs the "abstract actions" this implies —
routing a task to an existing project, or recognizing that a task needs a
brand-new project (local directory, optionally a GitHub repo) and spawning a
fresh agent for it. Also: simplify the TUI, which has grown three views and
~9 keybindings, back down to a single list.

## Non-goals

- No new fields, tags, or statuses on `Task`. Routing intent is expressed in
  plain title/notes text, read and judged by the orchestrator (an LLM), not
  parsed by a classifier.
- No live pane-availability polling before delivering a task to an existing
  project. Delivery to an existing project is purely `expqueue edit --project
  <name>`, leaving the task queued; sessions already in that project pull
  their own next task via `expqueue pop --project <name>` (pull model).
- No per-project queue files — the shared `queue.json` + `--project` scoped
  `pop`/`list` (already shipped) remains the only queue.
- No project scaffolding/template beyond `git init` on an empty directory.

## Part 1: Orchestrator-driven task triage

### Task intake (unchanged)

`expqueue push "<title>" [--notes "..."]` — no schema change. A task pushed
without `--project` has `project: null` and sits in the shared queue. This
null value is the implicit signal "awaiting orchestrator triage" — not a
new field, just the existing default.

### New capability: `expqueue project add --init-dir`

Today, `project add <name> <directory>` only *registers* a directory path —
it does not validate or require that the directory already exists (it will
happily register a nonexistent path). Add an `--init-dir` flag: when the
target directory does not exist, create it (`mkdir -p`) and run `git init`
inside it before registering; if it already exists, register as-is (no
`git init` — don't reinitialize a directory that might already be a repo or
contain files). Composes with the existing `--repo <owner/name>
[--create-repo]` flags — `--create-repo` already calls `ensure_gh_repo`,
which is reused unchanged. This is the only new expqueue code path in this
design; everything else is orchestrator (skill) behavior.

Without `--init-dir`, behavior is identical to today (register the path
as-is, no directory creation, no existence check) — fully backward
compatible.

### Orchestrator triage step (skill behavior, not new expqueue code)

Each orchestrator-loop cycle, in addition to the existing steps, for every
`queued` task with `project: null`:

1. **Read the task's title/notes** and judge intent against `expqueue
   project list --json`.
2. **Matches an existing project** → `expqueue edit <id> --project <name>`.
   Task stays `queued`; delivery is implicit — whichever session in that
   project's workspace next runs `expqueue pop --project <name>` picks it
   up. No pane-poking, no `c11 send`.
3. **Needs a brand-new project** — the human signals this in plain language
   in the task text (e.g. "new repo for this", "remote project", "spin up a
   fresh project for X"). The orchestrator:
   - Picks a project name and local directory (default
     `~/workplace/<name>`).
   - Runs `expqueue project add <name> <dir> --init-dir` — add `--repo
     <owner/name> --create-repo` if the task text implies GitHub-backed
     ("remote project" or equivalent); otherwise local-only.
   - `expqueue edit <id> --project <name>`.
   - Spawns a fresh agent per the existing c11 orchestration-skill pattern:
     `c11 new-workspace --cwd <dir>`, then launch `claude
     --dangerously-skip-permissions "<task prompt>"` as a one-shot argv
     launch (no ready-state race — see c11 skill's "Preferred — one-shot
     prompt via claude argv"). The task's title+notes become the initial
     prompt; the new session owns the task immediately, so no separate
     `pop` handoff is needed for this path.
   - New workspace matches the existing "one workspace per project"
     convention, so `expqueue project panes <name>` finds it for free from
     that point on.
4. **Ambiguous** — cannot confidently judge (1) or (2) — leave the task
   `queued` and unassigned, and escalate to the user rather than guess. This
   follows the same "never silently decide for the user on real
   consequences" rule already in the skill for hard decisions.

### Why this shape

- Keeps expqueue itself a thin, testable data layer (queue + registry);
  all "abstract action" judgment lives in the orchestrator's own reasoning,
  matching the user's explicit framing ("the orchestrator will handle the
  abstract... creating a new project... spawning and prompting child
  agent").
- No tag vocabulary to maintain or teach the orchestrator to parse — the
  user tried and explicitly backed out of adding tags mid-design ("no tags").
- Reuses two things that already exist rather than inventing new ones:
  `ensure_gh_repo` (repo creation) and the c11 orchestration skill's
  documented spawn pattern (workspace + one-shot argv launch).

## Part 2: TUI simplification

### Current state

Three views (Queue / State / Config) with a view-switching bar (`1`/`2`/`3`/
`Tab`), ~9 keybindings, a per-project dashboard (State) and a settings
screen (Config).

### New state

- **Cut State and Config views entirely.** Remove the view bar, the
  `active_view` reactive, `VIEWS`/`VIEW_LABEL`, and the state-table/
  config-body widgets and their refresh methods.
- **Single view: the task list.** Same visual structure as today's Queue
  view — RUNNING / QUEUED / COMPLETED section headers, status icon column,
  project column — since that grouping is already legible and the user
  confirmed keeping it.
- **Keep the project column and `p` assign keybinding.** More relevant now,
  not less: with orchestrator triage in play, "project column empty" now
  visibly means "awaiting triage," not just "nobody assigned it."
- **Keep all existing queue keybindings**: `a` add, `e` edit title, `s`
  start, `d` done, `x` drop, `r` requeue, `p` assign project, `D` delete,
  `/` cycle status filter, `q` quit. Drop only the view-navigation bindings
  (`1`, `2`, `3`, `tab`) and their handlers.
- `ConfigStore`/`ProjectStore` still back the app (default-project-on-add
  behavior, project name hints in the assign modal) — only the dedicated
  Config *screen* goes away, not the config file or its use as a default.

### What's explicitly out of scope

- No redesign of the modal/input pattern, colors, or table styling — the
  ask was to remove views, not restyle the surviving one.
- `ConfigStore.default_project` keeps being applied to new tasks added via
  `a` — there's just no UI screen to edit it anymore. (If this turns out to
  matter, editing the config file directly or via a future CLI flag remains
  available; not adding a command for it now since it wasn't asked for.)

## Testing

- `expqueue/panes.py`, `store.py` tests already cover pane discovery and
  scoped pop — unaffected by this change.
- New: `project add --init-dir` tests — creates a fresh temp directory path
  that doesn't exist yet, verify it's created with a `.git` directory inside,
  and registered; verify `--init-dir` on an already-existing directory
  registers it without touching/reinitializing it; verify plain `project add`
  (no flag) is unchanged — still registers a nonexistent path without
  creating anything.
- TUI: no existing test coverage for `tui.py` (Textual apps aren't unit
  tested here today) — verify manually via `uv run expqueue-tui` after
  the cut, confirming the queue view behaves identically minus the removed
  view-switching chrome.
- Orchestrator triage logic lives in the skill (prose instructions for an
  LLM), not in testable Python — no unit tests apply; verification is
  behavioral (watch a real orchestrator cycle route a task).
