# Orchestrator triage + TUI simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `expqueue project add --init-dir` (create-or-register a project
directory + optional GitHub repo), teach the `orchestrator-loop` skill to
triage unassigned queued tasks (route to an existing project or stand up a
brand-new one and spawn an agent), and cut the TUI back to a single grouped
task list by removing the State and Config views.

**Architecture:** Two independent, separately-shippable changes sharing one
plan. Part 1 touches `expqueue/projects.py` + `expqueue/cli.py` (one new
flag) and `skills/orchestrator-loop/SKILL.md` (prose-only — no new Python).
Part 2 is a subtractive edit to `expqueue/tui.py` (remove view-switching
machinery and the two secondary views), with no changes to `store.py`,
`projects.py`, or `config.py`.

**Tech Stack:** Python 3.14, argparse, pytest, Textual (TUI), `git`/`gh` CLI
subprocess calls (existing pattern in `projects.py`).

**Spec:** `docs/superpowers/specs/2026-07-15-orchestrator-triage-and-tui-simplification-design.md`

---

## Task 1: `ProjectStore.add` supports directory creation

**Files:**
- Modify: `expqueue/projects.py:88-96` (the `add` method)
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_store.py` (near the existing `test_project_store_*` tests):

```python
def test_project_store_init_dir_creates_missing_directory(tmp_path: Path) -> None:
    project_store = ProjectStore(path=tmp_path / "projects.json")
    target = tmp_path / "new-project"
    assert not target.exists()
    project = project_store.add("demo", str(target), init_dir=True)
    assert target.is_dir()
    assert (target / ".git").is_dir()
    assert project.directory == str(target)


def test_project_store_init_dir_leaves_existing_directory_alone(tmp_path: Path) -> None:
    project_store = ProjectStore(path=tmp_path / "projects.json")
    target = tmp_path / "already-here"
    target.mkdir()
    marker = target / "marker.txt"
    marker.write_text("keep me")
    project_store.add("demo", str(target), init_dir=True)
    assert marker.read_text() == "keep me"
    assert not (target / ".git").exists()


def test_project_store_add_without_init_dir_does_not_create_directory(tmp_path: Path) -> None:
    project_store = ProjectStore(path=tmp_path / "projects.json")
    target = tmp_path / "never-created"
    project = project_store.add("demo", str(target))
    assert not target.exists()
    assert project.directory == str(target)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/divkov/workplace/expqueue && uv run pytest tests/test_store.py -k init_dir -v`
Expected: 3 FAIL with `TypeError: add() got an unexpected keyword argument 'init_dir'`

- [ ] **Step 3: Implement `init_dir` in `ProjectStore.add`**

In `expqueue/projects.py`, replace the `add` method:

```python
    def add(
        self, name: str, directory: str, repo: str | None = None, init_dir: bool = False
    ) -> Project:
        resolved = Path(directory).expanduser()
        if init_dir and not resolved.exists():
            resolved.mkdir(parents=True)
            subprocess.run(["git", "init", str(resolved)], check=True, capture_output=True)
        project = Project(name=name, directory=str(resolved), repo=repo)
        with self._locked():
            items = self._read_raw()
            if any(d["name"] == name for d in items):
                raise ValueError(f"project already exists: {name}")
            items.append(project.to_dict())
            self._write_raw(items)
        return project
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/divkov/workplace/expqueue && uv run pytest tests/test_store.py -v`
Expected: all PASS (existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add expqueue/projects.py tests/test_store.py
git commit -m "Add init_dir option to ProjectStore.add for create-or-register"
```

---

## Task 2: `expqueue project add --init-dir` CLI flag

**Files:**
- Modify: `expqueue/cli.py:1-15` (module docstring), `:94-109` (`cmd_project_add`), `:196-205` (parser)

- [ ] **Step 1: Update `cmd_project_add` to pass through `init_dir`**

In `expqueue/cli.py`, replace `cmd_project_add`:

```python
def cmd_project_add(args: argparse.Namespace) -> None:
    pstore = ProjectStore()
    if args.create_repo and args.repo:
        try:
            created = ensure_gh_repo(args.repo)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        if created:
            print(f"created gh repo {args.repo}")
    try:
        project = pstore.add(args.name, args.directory, repo=args.repo, init_dir=args.init_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"[{project.name}] dir={project.directory} repo={project.repo or '-'}")
```

- [ ] **Step 2: Add the `--init-dir` flag to the parser**

In `expqueue/cli.py`, inside `build_parser`, update the `p_project_add`
block:

```python
    p_project_add = project_sub.add_parser("add", help="register a project")
    p_project_add.add_argument("name")
    p_project_add.add_argument("directory")
    p_project_add.add_argument("--repo", default=None, help="GitHub repo, e.g. owner/name")
    p_project_add.add_argument(
        "--create-repo",
        action="store_true",
        help="create the GitHub repo via `gh` if it doesn't exist",
    )
    p_project_add.add_argument(
        "--init-dir",
        action="store_true",
        help="create the local directory (and run `git init`) if it doesn't exist yet",
    )
    p_project_add.set_defaults(func=lambda store, args: cmd_project_add(args))
```

- [ ] **Step 3: Update the module docstring usage block**

In `expqueue/cli.py`, update line 12 of the docstring:

```
  expqueue project add <name> <directory> [--repo <owner/name>] [--create-repo] [--init-dir]
```

- [ ] **Step 4: Manually verify end-to-end**

Run:
```bash
cd /Users/divkov/workplace/expqueue
export EXPQUEUE_PROJECTS_PATH=$(mktemp -d)/projects.json
uv run expqueue project add demo /tmp/expqueue-plan-check --init-dir
ls -la /tmp/expqueue-plan-check/.git && echo "git init confirmed"
uv run expqueue project list
rm -rf /tmp/expqueue-plan-check
```
Expected: prints `[demo] dir=/tmp/expqueue-plan-check repo=-`, confirms
`.git` exists, and `project list` shows the registered project.

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/divkov/workplace/expqueue && uv run pytest -v`
Expected: all PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add expqueue/cli.py
git commit -m "Add --init-dir flag to expqueue project add"
```

---

## Task 3: Update README for `--init-dir`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Projects section**

In `README.md`, find this block:

```
uv run expqueue project add demo ~/workplace/demo [--repo me/demo] [--create-repo]
uv run expqueue project list [--json]
uv run expqueue project panes demo [--json]
```

Replace with:

```
uv run expqueue project add demo ~/workplace/demo [--repo me/demo] [--create-repo] [--init-dir]
uv run expqueue project list [--json]
uv run expqueue project panes demo [--json]
```

Then, right after the existing `--create-repo` explanation paragraph
(the one starting "`--create-repo` creates the GitHub repo..."), add a new
paragraph:

```
`--init-dir` creates the local directory (and runs `git init` inside it) if it doesn't already exist, so `project add` can bring a brand-new project into existence rather than only registering one that's already there. If the directory already exists, `--init-dir` registers it as-is without touching its contents.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document --init-dir in README"
```

---

## Task 4: Orchestrator-loop skill — triage step

**Files:**
- Modify: `skills/orchestrator-loop/SKILL.md`

- [ ] **Step 1: Add a triage step to the main cycle**

In `skills/orchestrator-loop/SKILL.md`, the "Cycle" section currently starts
with:

```
1. **Check expqueue**: `expqueue list --json`. Any `queued` items are new
   work someone added since last cycle. For a task with a `project`
   assignment, prefer `expqueue project panes <project>` to find that
   project's own workspace/panes first (see "Allocating a task to a
   project" below) rather than scanning the whole fleet. Once a target
   session is picked (see step 3), deliver the task via `c11 send` +
   `c11 send-key enter` and tell that session to `expqueue pop --project
   <name>` (or plain `expqueue pop` for unassigned tasks) / `done` it.
```

Replace it with (renumbering this as step 1, inserting triage as step 2, and
bumping the old steps 2-4 to 3-5):

```
1. **Check expqueue**: `expqueue list --json`. Any `queued` items are new
   work someone added since last cycle.

2. **Triage unassigned tasks.** For every `queued` task with `project:
   null`, read its title/notes and judge against `expqueue project list
   --json`:
   - **Matches an existing project** (the task clearly relates to a
     project you already know about — by name, by directory, by subject
     matter) → `expqueue edit <id> --project <name>`. Leave it `queued`;
     delivery is implicit — whichever session in that project's workspace
     next runs `expqueue pop --project <name>` will pick it up. Do not
     `c11 send` into a pane for this case.
   - **Explicitly needs a brand-new project** — the task's own text says
     so in plain language (e.g. "new repo for this", "remote project",
     "spin up a fresh project for X"). Only create a new project when the
     task itself asks for one; a task merely lacking a project match is
     NOT enough justification — see the ambiguous case below.
     1. Pick a project name and local directory (default
        `~/workplace/<name>`).
     2. `expqueue project add <name> <dir> --init-dir` — add `--repo
        <owner/name> --create-repo` only if the task text implies
        GitHub-backed (e.g. says "remote project"); otherwise local-only.
     3. `expqueue edit <id> --project <name>`.
     4. Spawn a fresh agent: `c11 new-workspace --cwd <dir>`, then launch
        `claude --dangerously-skip-permissions "<task title + notes as the
        prompt>"` as a one-shot argv launch (see the c11 skill's
        "Preferred — one-shot prompt via claude argv" pattern — no
        ready-state race, no polling). The new session receives the task
        as its initial prompt, so it owns the work immediately; do not
        also leave the task queued for a `pop`.
     5. Name the new workspace/tab per the c11 orchestration skill's
        tab-naming convention before or immediately after launch.
   - **Ambiguous** — you cannot confidently place it in either bucket
     above → leave it `queued` and unassigned, and escalate to the user
     (see step 5) rather than guess. Do not create a project speculatively.

3. **Poll the c11 workplace workspace**: `c11 tree --workspace <ref> --no-layout --report`
   to enumerate panes/surfaces, then `c11 read-screen --surface <ref>` on each
   active `claude-code`/`codex` surface to see its tail output.
```

- [ ] **Step 2: Renumber the remaining cycle steps**

Immediately following the block just replaced, the skill has (old numbering)
steps 3 and 4. Update their leading numbers to 4 and 5 respectively — i.e.
change:

```
3. **Classify each surface's state** and act:
```
to:
```
4. **Classify each surface's state** and act:
```

and change:

```
4. **Report back tersely**: what's newly queued, what you drove, what you
   escalated. Don't re-list surfaces that are unchanged and still running.
```
to:
```
5. **Report back tersely**: what's newly queued, what you triaged (routed
   or created), what you drove, what you escalated. Don't re-list surfaces
   that are unchanged and still running.
```

- [ ] **Step 3: Update the "Allocating a task to a project" section header context**

That section (further down the file) currently starts with `` `expqueue
project panes <name>` finds c11 workspaces... `` — leave its content as-is,
it's still accurate for the "matches an existing project" delivery path.
No edit needed there beyond what steps 1-2 already changed above it.

- [ ] **Step 4: Add the new project-add command to "Useful commands"**

In the `## Useful commands` code block at the bottom of the file, add one
line after the existing `expqueue project panes demo --json` line:

```
expqueue project add <name> <dir> --init-dir [--repo <owner/name> --create-repo]
```

- [ ] **Step 5: Read the full file back and sanity-check numbering/flow**

Run: `cat skills/orchestrator-loop/SKILL.md`
Expected: cycle steps are numbered 1-5 with no gaps or duplicates; the
triage step (2) reads coherently between "check expqueue" (1) and "poll c11"
(3).

- [ ] **Step 6: Commit**

```bash
git add skills/orchestrator-loop/SKILL.md
git commit -m "Teach orchestrator-loop to triage unassigned tasks to projects"
```

---

## Task 5: TUI — remove State and Config views

**Files:**
- Modify: `expqueue/tui.py`

- [ ] **Step 1: Rewrite the module docstring**

Replace lines 1-27 of `expqueue/tui.py` (the module docstring) with:

```python
"""Textual TUI for the experiment queue.

A single view: tasks grouped into RUNNING / QUEUED / COMPLETED sections.

Keybindings:
  a         add a new task
  e         edit selected task's title
  d         mark selected task done
  x         drop selected task
  s         mark selected task in_progress ("start")
  r         requeue selected task (back to queued)
  p         assign selected task to a project (existing project, or leave
            unset to keep it in the general/unassigned queue)
  D         delete selected task
  /         filter by status (cycles: all -> queued -> in_progress -> done -> dropped)
  q         quit
"""
```

- [ ] **Step 2: Remove `VIEWS`/`VIEW_LABEL` and the `_relative_time` helper**

`_relative_time` is only used by `refresh_state_view` (being removed in a
later step) — delete it along with `VIEWS`/`VIEW_LABEL`. Remove these lines:

```python
VIEWS = ["queue", "state", "config"]
VIEW_LABEL = {"queue": "Queue", "state": "State", "config": "Config"}
```

and:

```python
def _relative_time(ts: float) -> str:
    delta = max(0, time.time() - ts)
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"
```

Also remove the now-unused `import time` at the top of the file (check
after this step that nothing else in the file uses `time` — it doesn't).

- [ ] **Step 3: Simplify the CSS block**

Replace the `CSS` class attribute (currently includes `#view-bar`,
`#status-bar`, `#config-body` rules) with:

```python
    CSS = """
    Screen {
        layout: vertical;
    }
    #status-bar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    """
```

- [ ] **Step 4: Remove view-navigation bindings**

In `BINDINGS`, remove these four entries:

```python
        Binding("1", "goto_queue", "Queue"),
        Binding("2", "goto_state", "State"),
        Binding("3", "goto_config", "Config"),
        Binding("tab", "cycle_view", "Next view", priority=True),
```

Leave the rest of `BINDINGS` (`a`, `e`, `d`, `x`, `s`, `r`, `p`, `D`, `/`,
`q`) unchanged.

- [ ] **Step 5: Remove the `active_view` reactive**

Delete:

```python
    active_view: reactive[str] = reactive("queue", init=False)
```

Leave `filter_status: reactive[str | None] = reactive(None, init=False)` in
place.

- [ ] **Step 6: Simplify `compose`**

Replace:

```python
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._view_bar_text(), id="view-bar")
        yield Static("filter: all", id="status-bar")
        yield DataTable(id="queue-table", cursor_type="row", zebra_stripes=True)
        yield DataTable(id="state-table", cursor_type="row", zebra_stripes=True)
        with Vertical(id="config-body"):
            yield Static(id="config-text")
        yield Footer()
```

with:

```python
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("filter: all", id="status-bar")
        yield DataTable(id="queue-table", cursor_type="row", zebra_stripes=True)
        yield Footer()
```

- [ ] **Step 7: Simplify `on_mount` and `refresh_all`**

Replace:

```python
    def on_mount(self) -> None:
        self._apply_view_visibility()
        self.refresh_all()
        self.set_interval(2.0, self.refresh_all)

    def refresh_all(self) -> None:
        self.refresh_table()
        self.refresh_state_view()
        self.refresh_config_view()
```

with:

```python
    def on_mount(self) -> None:
        self.set_focus(self.query_one("#queue-table", DataTable))
        self.refresh_table()
        self.set_interval(2.0, self.refresh_table)
```

- [ ] **Step 8: Remove the "view switching" section entirely**

Delete this whole block (the `# -- view switching --` section header through
`action_cycle_view`):

```python
    # -- view switching -----------------------------------------------

    def _view_bar_text(self) -> str:
        parts = []
        for i, v in enumerate(VIEWS, start=1):
            label = f"[{i}] {VIEW_LABEL[v]}"
            if v == self.active_view:
                label = f"*{label}*"
            parts.append(label)
        return "  ".join(parts)

    def _apply_view_visibility(self) -> None:
        queue_table = self.query_one("#queue-table", DataTable)
        state_table = self.query_one("#state-table", DataTable)
        config_body = self.query_one("#config-body", Vertical)
        status_bar = self.query_one("#status-bar", Static)

        queue_table.display = self.active_view == "queue"
        status_bar.display = self.active_view == "queue"
        state_table.display = self.active_view == "state"
        config_body.display = self.active_view == "config"

        bar = self.query_one("#view-bar", Static)
        bar.update(self._view_bar_text())

        if self.active_view == "queue":
            self.set_focus(queue_table)
        elif self.active_view == "state":
            self.set_focus(state_table)

    def watch_active_view(self, value: str) -> None:
        self._apply_view_visibility()
        self.refresh_all()

    def action_goto_queue(self) -> None:
        self.active_view = "queue"

    def action_goto_state(self) -> None:
        self.active_view = "state"

    def action_goto_config(self) -> None:
        self.active_view = "config"

    def action_cycle_view(self) -> None:
        idx = VIEWS.index(self.active_view)
        self.active_view = VIEWS[(idx + 1) % len(VIEWS)]
```

- [ ] **Step 9: Remove all `if self.active_view != "queue": return` guards**

In the `# -- queue view --` section, every `action_*` method currently opens
with a guard like:

```python
        if self.active_view != "queue":
            return
```

Remove that guard from each of: `action_cycle_filter`, `action_add_task`,
`action_mark_done`, `action_mark_dropped`, `action_mark_started`,
`action_requeue`, `action_assign_project`, `action_delete_task`. These
methods now run unconditionally since there's only one view.

- [ ] **Step 10: Simplify `action_edit_task`**

Replace:

```python
    def action_edit_task(self) -> None:
        if self.active_view == "config":
            self._edit_default_project()
            return
        if self.active_view != "queue":
            return
        task_id = self._selected_id()
```

with:

```python
    def action_edit_task(self) -> None:
        task_id = self._selected_id()
```

(the rest of the method body is unchanged)

- [ ] **Step 11: Remove the state view section**

Delete this whole block:

```python
    # -- state view -------------------------------------------------------

    def refresh_state_view(self) -> None:
        table = self.query_one("#state-table", DataTable)
        table.clear(columns=True)
        table.add_columns("project", "tasks", "last status", "last touched")

        tasks = self.store.list()
        by_project: dict[str, list[Task]] = {}
        for t in tasks:
            by_project.setdefault(t.project or UNASSIGNED, []).append(t)

        known_names = [p.name for p in self.project_store.list()]
        ordered_names = known_names + [n for n in by_project if n not in known_names]

        for name in ordered_names:
            group = by_project.get(name, [])
            if not group:
                table.add_row(name, "0", "-", "-")
                continue
            latest = max(group, key=lambda t: t.updated_at)
            table.add_row(
                name,
                str(len(group)),
                latest.status,
                _relative_time(latest.updated_at),
            )
```

- [ ] **Step 12: Remove the config view section**

Delete this whole block:

```python
    # -- config view -------------------------------------------------------

    def refresh_config_view(self) -> None:
        cfg = self.config_store.load()
        text = self.query_one("#config-text", Static)
        lines = [
            "[b]expqueue configuration[/b]",
            "",
            f"queue path:     {self.store.path}",
            f"projects path:  {self.project_store.path}",
            f"config path:    {self.config_store.path}",
            "",
            f"default project for new tasks: {cfg.default_project or UNASSIGNED}",
            "",
            "press 'e' to edit the default project (blank = unassigned)",
        ]
        text.update("\n".join(lines))

    def _edit_default_project(self) -> None:
        cfg = self.config_store.load()

        def _on_value(value: str | None) -> None:
            if value is None:
                return
            self.config_store.set_default_project(value or None)
            self.refresh_config_view()

        self.push_screen(
            InputModal("Default project (blank = unassigned):", initial=cfg.default_project or ""),
            _on_value,
        )
```

- [ ] **Step 13: Remove the now-unused `Vertical` import**

`Vertical` was only used by `InputModal`'s dialog container and the removed
`#config-body`. Check: `InputModal.compose` still uses `Vertical` for its
own dialog — **keep** the import. (No action needed here; this step exists
to make the check explicit so the next step doesn't over-delete.)

- [ ] **Step 14: Verify the file is internally consistent**

Run: `cd /Users/divkov/workplace/expqueue && python -c "import ast; ast.parse(open('expqueue/tui.py').read())"`
Expected: no output (parses cleanly)

Run: `cd /Users/divkov/workplace/expqueue && grep -n "active_view\|VIEWS\|VIEW_LABEL\|state-table\|config-body\|config-text\|view-bar\|_relative_time\|refresh_state_view\|refresh_config_view\|_edit_default_project\|_apply_view_visibility\|_view_bar_text" expqueue/tui.py`
Expected: no output (all removed identifiers are gone)

- [ ] **Step 15: Manually verify the TUI still runs**

Run: `cd /Users/divkov/workplace/expqueue && timeout 3 uv run expqueue-tui || true`
Expected: launches without a traceback (it will exit via the timeout since
it's an interactive TUI — absence of a Python traceback in the output is
the pass signal). Then run it for real and confirm interactively:
```bash
uv run expqueue-tui
```
Confirm: single task list with RUNNING/QUEUED/COMPLETED headers, `a` adds a
task, `p` assigns a project, `/` cycles the status filter, `q` quits. No `1`/
`2`/`3`/`Tab` view switching exists (pressing `1`/`2`/`3` does nothing; Textual
will just report no binding).

- [ ] **Step 16: Run full test suite**

Run: `cd /Users/divkov/workplace/expqueue && uv run pytest -v`
Expected: all PASS — `tui.py` has no existing unit test coverage, so this
confirms only that the unrelated `store`/`projects`/`panes` tests still pass.

- [ ] **Step 17: Commit**

```bash
git add expqueue/tui.py
git commit -m "TUI: remove State and Config views, single task list only"
```

---

## Task 6: README — reflect single-view TUI

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the TUI section**

In `README.md`, replace this whole block:

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
```

with:

```
## TUI (human)

```
uv run expqueue-tui
```

A single view: tasks grouped into visual sections (RUNNING / QUEUED / COMPLETED), each row showing an icon + text status and a project column. Tasks with no project sit in the general/unassigned queue (shown as `(unassigned)`) — this is also the orchestrator's triage signal: an unassigned queued task is one it hasn't routed to a project yet. Auto-refreshes every 2s so it picks up changes made by an agent via the CLI.

Keys: `a` add, `e` edit title, `s` start, `d` done, `x` drop, `r` requeue, `p` assign to an existing project (blank clears it back to unassigned), `D` delete, `/` cycle status filter, `q` quit.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Update README for single-view TUI"
```

---

## Task 7: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `cd /Users/divkov/workplace/expqueue && uv run pytest -v`
Expected: all tests PASS (existing panes/store/project tests + the 3 new
`init_dir` tests from Task 1)

- [ ] **Step 2: Confirm CLI help text is coherent**

Run:
```bash
cd /Users/divkov/workplace/expqueue
uv run expqueue project add --help
uv run expqueue --help
```
Expected: `--init-dir` appears in `project add --help`; top-level help is
unchanged otherwise.

- [ ] **Step 3: Git status check**

Run: `cd /Users/divkov/workplace/expqueue && git status && git log --oneline -10`
Expected: working tree clean, 7 new commits since the last merged PR
(Tasks 1-6 plus this verification producing no new commit).
