# tq: task queue tightly coupled to a persistent orchestrator

## Context

`expqueue` (this project) is a file-backed task queue: a JSON store guarded by
flock, a CLI for agents, and a Textual TUI for the human. Today's model:

- **No persistent orchestrator process.** `orchestrator-loop` is a *skill* —
  prose instructions an LLM follows when invoked, typically by a `/loop` cron
  firing a fresh one-shot agent each cycle. `orchestrator.py`'s `claim`/
  `release` exists only to stop two cron-fired cycles from stacking (20-minute
  TTL treated as "abandoned").
- **No recorded pane bindings.** `project panes <name>` rediscovers candidate
  c11 workspaces live on every call, by matching workspace cwd against the
  project's registered directory. Nothing is persisted.
- **Pull delivery.** The orchestrator routes a task to a project
  (`edit --project`) and stops; the task sits `queued` until some session in
  that project's workspace calls `pop --project <name>` itself.
- **One workspace per project**, following c11's own convention — discovery
  depends on this convention holding.
- **Three-view TUI** (Queue / Projects, previously also State/Config) built
  as full-screen tables with `1`/`2`/`Tab` view switching.

This has produced real friction (see task bc8988a3, and the "duplicate crons
+ `Unknown skill` error every orch cycle" note from 2026-07-15): each cron
tick re-spawns a fresh agent with no memory of prior cycles, so nothing
persists across ticks except what's written to disk.

We're rebuilding this as **tq**: the queue becomes tightly coupled to a
single persistent orchestrator agent, task delivery becomes push-based into
recorded pane bindings, and all tq-managed panes live in one shared,
configurable c11 workspace. The TUI is rebuilt from scratch around this
model rather than retrofitted.

Renaming `expqueue` → `tq` is in scope (binary names, env var prefixes,
package name) since this is a clean rebuild, not an incremental patch.

## Non-goals

- No in-tq steering (sending arbitrary text into a project's pane from the
  TUI). Explicitly dropped from scope — jump to the real c11 pane to type.
- No embedded live-tail of agent output in the TUI. The Projects view shows
  status only (idle/working/last activity, bound pane refs); watching full
  output means switching to the real pane.
- No multi-orchestrator / multi-workspace support. One shared workspace, one
  orchestrator, configured once.
- No change to the underlying flock-guarded JSON storage strategy — still
  appropriate at this scale, just with schema additions.
- No project scaffolding beyond `git init` on an empty directory (unchanged
  from today).

## Architecture

### The orchestrator is a persistent, singleton, cron-nudged agent

The orchestrator is a real c11 surface running `claude
--dangerously-skip-permissions`, whose ref (`workspace_ref` + `surface_ref`)
is recorded in tq's config. It is **not** a self-looping process — it
finishes each turn and goes idle, the same as any other Claude Code session.
A cron (`/loop`, e.g. every 2–5 minutes) sends a short nudge into its
existing pane: `c11 send --workspace <w> --surface <s> "check tq now"`. Because
it's the *same* pane across ticks, conversation history and context
accumulate turn over turn — the cron is a wake-up bell, not a respawn.

**Ensuring the orchestrator is alive** (checked by the TUI on startup, and by
the cron before nudging):

1. Read `config.json` for `orchestrator.workspace_ref` /
   `orchestrator.surface_ref`. If unset → never set up, go to step 3.
2. Verify the recorded surface still exists: `c11 tree --workspace <ref>
   --no-layout`. Found → reuse, done. "Surface not found" or command
   failure → treat as dead, go to step 3.
3. Spawn: ensure the shared workspace exists (create if
   `config.json`'s `shared_workspace_ref` is also unset — see below), add a
   surface to it via `c11 new-surface --pane <pane> --workspace <ref>`,
   launch `claude --dangerously-skip-permissions` with a one-shot prompt
   (argv form, per the c11 orchestration pattern — no ready-state race),
   record the new `workspace_ref`/`surface_ref` back into `config.json`.

This reuses the existing `spawn_background_agent` lazy-init/stale-render
workarounds from `panes.py` (task bc8988a3) — those quirks are about c11's
surface bring-up, not about which workspace the surface lands in, so they
apply unchanged.

The old `claim`/`release` cooperative lock is repurposed: instead of guarding
a 20-minute "cycle ownership" window, it becomes a short-TTL (e.g. 60s) mutex
purely around the "ensure orchestrator" spawn sequence itself, so two
processes racing to notice a dead orchestrator don't both spawn a
replacement. Once ensure-orchestrator completes (or fails), release.

### One shared, configurable c11 workspace

`config.json` gains `shared_workspace_ref`. If unset, the first
"ensure orchestrator" spawn creates a fresh workspace and records its ref;
if set (including by hand, pointing at an existing workspace), tq reuses it.
This workspace holds:

- **The orchestrator's own surface.**
- **One surface per active project** — created on first delivery to that
  project (see below), reused after.

This replaces the one-workspace-per-project convention. Discovery no longer
depends on cwd-matching; it depends on tq's own recorded bindings.

### Project→pane binding lives in tq, not discovered live

`Project` gains `workspace_ref: str | None` and `surface_ref: str | None`.
Binding happens once, lazily, the first time the orchestrator needs to
deliver a task to a project with no existing binding:

1. `c11 new-surface --pane <shared-workspace's pane> --workspace
   <shared_workspace_ref> --cwd <project.directory>`.
2. Launch the agent one-shot (argv form) with the task as its initial prompt
   — the new session owns the task immediately.
3. Record `workspace_ref`/`surface_ref` onto the `Project` in `projects.json`.

Subsequent deliveries to the same project reuse the recorded binding directly
— no live c11 scan. Before each use, the orchestrator verifies the binding is
still live the same way it verifies its own pane (`c11 tree`); a missing
surface means "re-bind" (go through the steps above again), not an error.

`project panes <name>` (today's live-discovery command) is removed — it
solved a problem (finding a pane you didn't record) that no longer exists
once binding is tq-owned. `project spawn` is replaced by the internal
bind-on-first-delivery flow above; it's no longer a standalone CLI verb since
the orchestrator is the only caller.

### Delivery is push, always

The pull model (`pop --project <name>` called by a session inside its own
project workspace) is removed. The orchestrator is the sole path work
reaches an agent:

1. For each `queued` task with a non-null `project`, check the project's
   bound surface's `activity` (`c11 get-metadata --key activity` — this is
   genuinely per-surface derived liveness, unlike the workspace-aggregated
   `list-status`, so it works correctly with multiple project surfaces
   sharing one workspace).
2. `idle` → `c11 send` the task's title+notes directly into that surface,
   mark the task `in_progress` (`update_status`), log an orchestrator
   breadcrumb.
3. `working` or binding missing/stale → leave `queued`, retry next tick.
4. No binding yet → bind (previous section), which delivers the first task
   as part of spawning.

`pop` is kept in the CLI (useful for manual/debug use — a human popping a
task by hand), but it's no longer part of the orchestrator's own flow, and
the README/skill no longer document it as the delivery mechanism.

### Task and Project triage (mostly unchanged from the 2026-07-15 design)

Unassigned (`project: null`) queued tasks are still triaged by the
orchestrator's own reasoning against `project list --json` — matches an
existing project, needs a new one (only when the task text says so
explicitly), or is ambiguous (leave unassigned, escalate to the user). This
logic is unchanged; only what happens *after* a task is assigned changes
(push instead of pull).

### Auto-confirming obvious in-flight questions

Beyond triage, each cycle the orchestrator also reads the screen
(`c11 read-screen`) of every project surface currently showing a
waiting-on-input state. Two cases:

- **The pane's own agent poses a question that already names a recommended
  option** (e.g. "I'd recommend X because... — proceed?", a numbered list
  with one marked "(recommended)"). The orchestrator drives it forward on
  its own: `c11 send` confirming the recommended option, no escalation. This
  is the same "drive straightforward continuations" behavior the current
  `orchestrator-loop` skill already documents for simple yes/no prompts —
  extended explicitly to cover "recommended option among several," which is
  equally unambiguous.
- **A question with no clear recommendation, or real architectural/
  consequential stakes** — leave it alone and escalate to the user, per the
  existing hard-decision rule. Judgment of "obvious" vs. "needs the human"
  is the orchestrator's own reasoning; this is prose guidance for the skill,
  not a classifier to build.

### Schema summary

```
Task            — unchanged (id, title, notes, status, project, timestamps)

Project         + workspace_ref: str | None
                + surface_ref: str | None
                (name, directory, repo, created_at unchanged)

Config          + shared_workspace_ref: str | None
                + orchestrator: {workspace_ref, surface_ref} | None
                (default_project unchanged)

Orchestrator    claim/release repurposed: short-TTL (60s) mutex around
  store           "ensure orchestrator" spawn, not a 20-minute cycle lock.
                events/log unchanged (still surfaced in the TUI).
```

### Renaming expqueue → tq

- Package `expqueue` → `tq`. Console scripts `expqueue`/`expqueue-tui` →
  `tq`/`tq-tui`.
- Env vars `EXPQUEUE_*` → `TQ_*` (`TQ_PATH`, `TQ_PROJECTS_PATH`,
  `TQ_CONFIG_PATH`, `TQ_ORCHESTRATOR_PATH`).
- Default data directory `~/workplace/.expqueue/` → `~/workplace/.tq/`.
- Skill `orchestrator-loop` → rewritten in place to describe the new
  persistent-agent + push-delivery + shared-workspace model (see below);
  keep it in `skills/` under a name reflecting its new role, e.g.
  `tq-orchestrator`.

## TUI: primitive, informational only

The TUI is not the control surface — the orchestrator is. tq's TUI exists to
visualize the two lists (tasks, projects) and give a trace of what the
orchestrator is doing/aware of. Deliberately plain: no new interaction model,
no split-pane, no per-task detail editing beyond what already exists.

Keep today's structure — a single task-list view (RUNNING/QUEUED/COMPLETED
sections, status icon, project column) plus a Projects view — and extend each
with orchestrator-derived facts rather than redesigning the shell:

- **Task list** (unchanged grouping/columns) — the project column is now
  more informative: it reflects tq-recorded assignment, and an unassigned row
  is a visible "awaiting orchestrator triage" signal, same as the
  2026-07-15 design already established.
- **Projects view** — gains, per project: local directory, repo (if any, i.e.
  "local" vs. "remote"), and the recorded pane binding (`workspace_ref` /
  `surface_ref`) with its live `idle`/`working`/`unknown` status pulled from
  `activity`. This is the "which projects and panes is the orchestrator aware
  of" insight — read straight from `projects.json`, no new live c11 scan.
- **Orchestrator activity panel** (already exists at the bottom of the Queue
  view) — kept as-is: most-recent breadcrumbs, now also covering bind/spawn
  and auto-confirm events, not just triage-routing ones.
- **Orchestrator health line** — one new small addition: alive/not-running,
  computed the same way `ensure_orchestrator` checks liveness (does the
  recorded pane still exist). Surfaced as a single status line, not a new
  view.
- No new keybindings beyond what's needed to view the above; no view
  redesign otherwise. Auto-refresh every 2s, unchanged.

## Testing

- `store.py`, `orchestrator.py` (repurposed claim semantics), `projects.py`
  (new fields) get unit tests same as today — pure JSON+flock logic, no c11
  dependency.
- `panes.py` binding logic (bind-on-first-delivery, liveness re-check) is
  testable by mocking the `c11` subprocess boundary, same pattern
  `test_panes.py` already uses.
- Orchestrator *behavior* (triage judgment, when to bind vs. reuse, push
  delivery) remains skill prose for an LLM — no unit tests, verified
  behaviorally by watching a real cycle.
- TUI: manual verification via `uv run tq-tui`, as today (no Textual test
  harness in this project).

## Migration

No live data to migrate cleanly (single-user, low-stakes queue) — this is
a rebuild. Existing `~/workplace/.expqueue/` data is abandoned in place, not
migrated; `~/workplace/.tq/` starts fresh. This is called out explicitly so
it isn't assumed to be a silent, automatic step.
