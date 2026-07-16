# tq Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `expqueue` as `tq`: a persistent, singleton orchestrator agent that pushes tasks directly into tq-recorded project↔pane bindings inside one shared c11 workspace, with a primitive, informational-only TUI.

**Architecture:** Rename the package/CLI/env vars from `expqueue`→`tq`. Add `workspace_ref`/`surface_ref` fields to `Project` and new `shared_workspace_ref`/`orchestrator` fields to `Config`. Replace live pane discovery (`panes.py`'s cwd-matching) with binding helpers that create-or-reuse a surface inside one shared workspace and persist the ref onto the `Project` record. Repurpose the existing `claim`/`release` cooperative lock from a 20-minute cycle-lock into a short-TTL spawn mutex. Rewrite the `orchestrator-loop` skill as `tq-orchestrator` describing the new persistent/push/auto-confirm model. Trim the TUI's Projects view and Queue view to surface the new pane-binding/health facts, without a layout redesign.

**Tech Stack:** Python 3.14, Textual (TUI), pytest, `c11` CLI (subprocess), flock-guarded JSON files (unchanged storage strategy).

---

## File structure

- `expqueue/` → renamed to `tq/` (directory rename via `git mv`).
  - `tq/store.py` — unchanged logic, just import path.
  - `tq/projects.py` — `Project` gains `workspace_ref`, `surface_ref`; `ProjectStore` gains `bind()`/`clear_binding()`.
  - `tq/config.py` — `Config` gains `shared_workspace_ref`, `orchestrator_workspace_ref`, `orchestrator_surface_ref`.
  - `tq/orchestrator.py` — `claim`/`release` TTL constant lowered; docstring updated to describe the new spawn-mutex role. No behavior-breaking change to the claim/release mechanics themselves (same code), just the constant and docs.
  - `tq/panes.py` — split: keep `C11Unavailable`, `_run_c11`, `_run_c11_raw` (all still needed). Remove `list_project_workspaces`, `_list_surfaces`, `_is_under`, `spawn_background_agent` (cwd-discovery and the workspace-scoped spawn primitive are both dead — replaced below). Add `surface_exists()`, `first_pane_ref()`, `ensure_shared_workspace()`, `create_surface()`, `launch_agent_in_surface()` (the generalized "launch claude one-shot into an existing surface, verify it landed" primitive — used by both the orchestrator's own pane and a project's pane), `bind_project_pane()` (composes `create_surface` + `launch_agent_in_surface` for the project case), `surface_activity()` (public, was private `_surface_activity` in the old file).
  - `tq/cli.py` — remove `project panes`/`project spawn` subcommands; keep everything else; add `orchestrator ensure` subcommand (invoked by the TUI on startup and by the cron before nudging) and `project bind` subcommand (invoked by the orchestrator to create+deliver a project's first pane).
  - `tq/tui.py` — Projects view gains pane-binding columns; Queue view gains an orchestrator health line; drop nothing else structurally.
- `tests/` — `test_store.py` keeps only `QueueStore` tests (rename import). `test_orchestrator.py` gains a TTL-specific test. `test_panes.py` rewritten for the new binding functions, old discovery tests removed. New `test_projects.py` holds the project-store tests relocated from `test_store.py` plus new binding tests (see Task 3). New `test_config.py` for the new `Config` fields (see Task 2).
- `skills/orchestrator-loop/SKILL.md` → renamed to `skills/tq-orchestrator/SKILL.md`, rewritten.
- `README.md` — updated for new commands/model.
- `pyproject.toml` — package name, script names.

---

### Task 1: Rename package `expqueue` → `tq`

**Files:**
- Modify: `pyproject.toml`
- Modify: `expqueue/__init__.py` → `tq/__init__.py` (git mv directory)
- Modify: `expqueue/store.py`, `expqueue/config.py`, `expqueue/orchestrator.py`, `expqueue/panes.py`, `expqueue/projects.py`, `expqueue/cli.py`, `expqueue/tui.py` → moved under `tq/`
- Modify: `tests/test_store.py`, `tests/test_orchestrator.py`, `tests/test_panes.py`

- [ ] **Step 1: Move the package directory**

```bash
git mv expqueue tq
```

- [ ] **Step 2: Update `pyproject.toml`**

```toml
[project]
name = "tq"
version = "0.1.0"
description = "File-backed task queue tightly coupled to a persistent c11 orchestrator"
requires-python = ">=3.14"
dependencies = [
    "textual>=8.2.8",
]

[project.scripts]
tq = "tq.cli:main"
tq-tui = "tq.tui:main"

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["tq"]
```

- [ ] **Step 3: Update env var names and default paths in `tq/store.py`**

Replace:
```python
DEFAULT_QUEUE_PATH = Path(
    os.environ.get("EXPQUEUE_PATH", Path.home() / "workplace" / ".expqueue" / "queue.json")
)
```
With:
```python
DEFAULT_QUEUE_PATH = Path(
    os.environ.get("TQ_PATH", Path.home() / "workplace" / ".tq" / "queue.json")
)
```

- [ ] **Step 4: Same rename in `tq/config.py`**

Replace:
```python
DEFAULT_CONFIG_PATH = Path(
    os.environ.get("EXPQUEUE_CONFIG_PATH", Path.home() / "workplace" / ".expqueue" / "config.json")
)
```
With:
```python
DEFAULT_CONFIG_PATH = Path(
    os.environ.get("TQ_CONFIG_PATH", Path.home() / "workplace" / ".tq" / "config.json")
)
```

- [ ] **Step 5: Same rename in `tq/orchestrator.py`**

Replace:
```python
DEFAULT_ORCHESTRATOR_PATH = Path(
    os.environ.get(
        "EXPQUEUE_ORCHESTRATOR_PATH",
        Path.home() / "workplace" / ".expqueue" / "orchestrator.json",
    )
)
```
With:
```python
DEFAULT_ORCHESTRATOR_PATH = Path(
    os.environ.get(
        "TQ_ORCHESTRATOR_PATH",
        Path.home() / "workplace" / ".tq" / "orchestrator.json",
    )
)
```

- [ ] **Step 6: Same rename in `tq/projects.py`**

Replace:
```python
DEFAULT_PROJECTS_PATH = Path(
    os.environ.get(
        "EXPQUEUE_PROJECTS_PATH",
        Path.home() / "workplace" / ".expqueue" / "projects.json",
    )
)
```
With:
```python
DEFAULT_PROJECTS_PATH = Path(
    os.environ.get(
        "TQ_PROJECTS_PATH",
        Path.home() / "workplace" / ".tq" / "projects.json",
    )
)
```

- [ ] **Step 7: Fix all internal imports**

In `tq/cli.py` and `tq/tui.py`, replace every `from expqueue.` with `from tq.`. In `tests/test_store.py`, `tests/test_orchestrator.py`, `tests/test_panes.py`, replace every `from expqueue.` with `from tq.`.

- [ ] **Step 8: Run the existing test suite to confirm the rename didn't break anything**

Run: `uv run pytest -v`
Expected: All existing tests pass (same count as before the rename — the rename is import-path-only at this point, no behavior change).

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Rename expqueue package to tq"
```

---

### Task 2: Add `Config` fields for shared workspace and orchestrator binding

**Files:**
- Modify: `tq/config.py`
- Test: `tests/test_config.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
from pathlib import Path

import pytest

from tq.config import Config, ConfigStore


@pytest.fixture
def store(tmp_path: Path) -> ConfigStore:
    return ConfigStore(path=tmp_path / "config.json")


def test_default_config_has_no_orchestrator_or_workspace(store: ConfigStore) -> None:
    config = store.load()
    assert config.shared_workspace_ref is None
    assert config.orchestrator_workspace_ref is None
    assert config.orchestrator_surface_ref is None


def test_set_shared_workspace_ref(store: ConfigStore) -> None:
    store.set_shared_workspace_ref("workspace:9")
    assert store.load().shared_workspace_ref == "workspace:9"


def test_set_orchestrator_pane(store: ConfigStore) -> None:
    store.set_orchestrator_pane("workspace:9", "surface:38")
    config = store.load()
    assert config.orchestrator_workspace_ref == "workspace:9"
    assert config.orchestrator_surface_ref == "surface:38"


def test_clear_orchestrator_pane(store: ConfigStore) -> None:
    store.set_orchestrator_pane("workspace:9", "surface:38")
    store.clear_orchestrator_pane()
    config = store.load()
    assert config.orchestrator_workspace_ref is None
    assert config.orchestrator_surface_ref is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `AttributeError` on `shared_workspace_ref` (field doesn't exist yet).

- [ ] **Step 3: Update `Config` and `ConfigStore` in `tq/config.py`**

Replace the `Config` dataclass:

```python
@dataclass
class Config:
    default_project: str | None = None
    shared_workspace_ref: str | None = None
    orchestrator_workspace_ref: str | None = None
    orchestrator_surface_ref: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Config":
        return Config(
            default_project=d.get("default_project"),
            shared_workspace_ref=d.get("shared_workspace_ref"),
            orchestrator_workspace_ref=d.get("orchestrator_workspace_ref"),
            orchestrator_surface_ref=d.get("orchestrator_surface_ref"),
        )
```

Add these methods to `ConfigStore` (after `set_default_project`):

```python
    def set_shared_workspace_ref(self, workspace_ref: str) -> Config:
        with self._locked():
            data = self._read_raw()
            data["shared_workspace_ref"] = workspace_ref
            self._write_raw(data)
            return Config.from_dict(data)

    def set_orchestrator_pane(self, workspace_ref: str, surface_ref: str) -> Config:
        with self._locked():
            data = self._read_raw()
            data["orchestrator_workspace_ref"] = workspace_ref
            data["orchestrator_surface_ref"] = surface_ref
            self._write_raw(data)
            return Config.from_dict(data)

    def clear_orchestrator_pane(self) -> Config:
        with self._locked():
            data = self._read_raw()
            data["orchestrator_workspace_ref"] = None
            data["orchestrator_surface_ref"] = None
            self._write_raw(data)
            return Config.from_dict(data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_config.py tq/config.py
git commit -m "Add shared workspace and orchestrator pane fields to Config"
```

---

### Task 3: Add pane binding fields to `Project`

**Files:**
- Modify: `tq/projects.py`
- Modify: `tests/test_store.py` (move project-store tests out)
- Test: `tests/test_projects.py` (new file — project-store tests relocated here plus new binding tests)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_projects.py` with the existing project-store tests moved from `tests/test_store.py`, plus new binding tests:

```python
from pathlib import Path

import pytest

from tq.projects import Project, ProjectStore


@pytest.fixture
def project_store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(path=tmp_path / "projects.json")


def test_project_store_add_and_list(project_store: ProjectStore) -> None:
    project_store.add("demo", "/tmp/demo", repo="me/demo")
    projects = project_store.list()
    assert len(projects) == 1
    assert projects[0] == Project(
        name="demo",
        directory="/tmp/demo",
        repo="me/demo",
        created_at=projects[0].created_at,
    )


def test_project_store_duplicate_name_raises(project_store: ProjectStore) -> None:
    project_store.add("demo", "/tmp/demo")
    with pytest.raises(ValueError):
        project_store.add("demo", "/tmp/other")


def test_project_store_duplicate_name_with_init_dir_does_not_create_directory(
    tmp_path: Path,
) -> None:
    project_store = ProjectStore(path=tmp_path / "projects.json")
    project_store.add("demo", str(tmp_path / "existing"))
    orphan = tmp_path / "orphan"
    with pytest.raises(ValueError):
        project_store.add("demo", str(orphan), init_dir=True)
    assert not orphan.exists()


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


def test_new_project_has_no_pane_binding(project_store: ProjectStore) -> None:
    project = project_store.add("demo", "/tmp/demo")
    assert project.workspace_ref is None
    assert project.surface_ref is None


def test_bind_sets_pane_refs(project_store: ProjectStore) -> None:
    project_store.add("demo", "/tmp/demo")
    bound = project_store.bind("demo", "workspace:9", "surface:38")
    assert bound.workspace_ref == "workspace:9"
    assert bound.surface_ref == "surface:38"
    assert project_store.get("demo").workspace_ref == "workspace:9"


def test_bind_unknown_project_returns_none(project_store: ProjectStore) -> None:
    assert project_store.bind("ghost", "workspace:9", "surface:38") is None


def test_clear_binding_resets_pane_refs(project_store: ProjectStore) -> None:
    project_store.add("demo", "/tmp/demo")
    project_store.bind("demo", "workspace:9", "surface:38")
    cleared = project_store.clear_binding("demo")
    assert cleared.workspace_ref is None
    assert cleared.surface_ref is None
```

Remove the six `test_project_store_*` functions from `tests/test_store.py` (they now live in `tests/test_projects.py`), along with the now-unused `project_store` fixture and `from tq.projects import Project, ProjectStore` import in that file. `tests/test_store.py` should end up containing only the `QueueStore`-focused tests (`test_push_and_pop` through `test_list_filters_by_status`) and the `store` fixture.

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_projects.py -v`
Expected: `test_new_project_has_no_pane_binding` etc. FAIL with `AttributeError: 'Project' object has no attribute 'workspace_ref'`. The relocated tests should already pass (no behavior change).

- [ ] **Step 3: Add binding fields and methods to `tq/projects.py`**

Replace the `Project` dataclass:

```python
@dataclass
class Project:
    name: str
    directory: str
    repo: str | None = None
    workspace_ref: str | None = None
    surface_ref: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Project":
        return Project(
            name=d["name"],
            directory=d["directory"],
            repo=d.get("repo"),
            workspace_ref=d.get("workspace_ref"),
            surface_ref=d.get("surface_ref"),
            created_at=d.get("created_at", time.time()),
        )
```

Add these methods to `ProjectStore` (after `add`):

```python
    def bind(self, name: str, workspace_ref: str, surface_ref: str) -> Project | None:
        with self._locked():
            items = self._read_raw()
            for d in items:
                if d["name"] == name:
                    d["workspace_ref"] = workspace_ref
                    d["surface_ref"] = surface_ref
                    self._write_raw(items)
                    return Project.from_dict(d)
        return None

    def clear_binding(self, name: str) -> Project | None:
        with self._locked():
            items = self._read_raw()
            for d in items:
                if d["name"] == name:
                    d["workspace_ref"] = None
                    d["surface_ref"] = None
                    self._write_raw(items)
                    return Project.from_dict(d)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_projects.py tests/test_store.py -v`
Expected: PASS (all tests in both files)

- [ ] **Step 5: Commit**

```bash
git add tests/test_projects.py tests/test_store.py tq/projects.py
git commit -m "Add pane binding fields to Project"
```

---

### Task 4: Repurpose the claim/release TTL as a short spawn mutex

**Files:**
- Modify: `tq/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Update the failing test for the new TTL**

In `tests/test_orchestrator.py`, `test_claim_succeeds_after_stale_ttl` already uses the `CLAIM_TTL_SECONDS` constant symbolically, so it doesn't need code changes — but add an explicit assertion the TTL itself is short, so a regression back to 20 minutes is caught:

```python
def test_claim_ttl_is_short() -> None:
    import expqueue.orchestrator as orchestrator_mod  # placeholder, fixed in step 3

    assert orchestrator_mod.CLAIM_TTL_SECONDS <= 120
```

(This import will be fixed to `tq.orchestrator` in the same edit — written this way here only to flag the exact line changing. Write the real file with `import tq.orchestrator as orchestrator_mod`.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py::test_claim_ttl_is_short -v`
Expected: FAIL — `assert 1200 <= 120` (current TTL is 20 minutes = 1200 seconds).

- [ ] **Step 3: Update `tq/orchestrator.py`**

Replace the constant and module docstring:

```python
"""File-backed orchestrator activity log and a short-lived spawn mutex.

The orchestrator is a persistent c11 agent, nudged by cron rather than
respawned each cycle (see the tq-orchestrator skill). `claim`/`release` no
longer guard a whole cycle's worth of work -- they guard only the brief
"ensure orchestrator is alive, spawn a replacement if not" sequence, so two
processes racing to notice a dead orchestrator pane don't both spawn one.

The claim is cooperative, not access control: it only prevents *cooperating*
callers (ones that call `claim`/`release` themselves) from racing a spawn.
It cannot stop an arbitrary session from spawning its own c11 workspace and
launching an agent directly -- there is no privilege boundary in this system
to enforce that against a non-cooperating process.
"""
```

Change:
```python
MAX_EVENTS = 20
CLAIM_TTL_SECONDS = 20 * 60  # a claim older than this is treated as abandoned
```
To:
```python
MAX_EVENTS = 20
CLAIM_TTL_SECONDS = 60  # a claim older than this is treated as abandoned
```

No other code changes — `claim`/`release`/`current_claim` logic is unchanged, only the TTL value and the docstring describing what the claim now guards.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: PASS (all tests, including the new `test_claim_ttl_is_short`)

- [ ] **Step 5: Commit**

```bash
git add tests/test_orchestrator.py tq/orchestrator.py
git commit -m "Shorten orchestrator claim TTL to a spawn mutex"
```

---

### Task 5: Replace `panes.py` live discovery with binding primitives

This is the largest task. `panes.py` currently does cwd-based discovery
(`list_project_workspaces`) and a spawn-and-verify primitive
(`spawn_background_agent`) scoped to *new* workspaces only. We keep the
proven spawn-and-verify logic but generalize it to add a surface to an
*existing* workspace/pane (the shared workspace), and add the higher-level
binding functions the orchestrator will call.

**Files:**
- Modify: `tq/panes.py`
- Modify: `tests/test_panes.py`

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_panes.py`:

```python
import json
from unittest.mock import patch

import pytest

from tq.panes import (
    C11Unavailable,
    bind_project_pane,
    ensure_shared_workspace,
    launch_agent_in_surface,
    surface_exists,
)


def _completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    class _Result:
        pass

    r = _Result()
    r.stdout = stdout
    r.returncode = returncode
    r.stderr = stderr
    return r


TREE_FOUND = {
    "windows": [
        {
            "workspaces": [
                {
                    "panes": [
                        {"ref": "pane:21", "surfaces": [{"ref": "surface:37", "title": "shell"}]}
                    ]
                }
            ]
        }
    ]
}


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_surface_exists_true_when_tree_succeeds(mock_run, mock_which) -> None:
    mock_run.return_value = _completed(stdout=json.dumps(TREE_FOUND))
    assert surface_exists("workspace:9", "surface:37") is True


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_surface_exists_false_when_surface_missing_from_tree(mock_run, mock_which) -> None:
    mock_run.return_value = _completed(stdout=json.dumps({"windows": []}))
    assert surface_exists("workspace:9", "surface:999") is False


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_surface_exists_false_when_workspace_command_fails(mock_run, mock_which) -> None:
    mock_run.return_value = _completed(returncode=1, stderr="Socket not found")
    assert surface_exists("workspace:9", "surface:37") is False


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_ensure_shared_workspace_creates_when_none_given(mock_run, mock_which) -> None:
    mock_run.return_value = _completed(stdout="OK workspace:9")
    ref = ensure_shared_workspace(existing_ref=None)
    assert ref == "workspace:9"
    args = mock_run.call_args.args[0]
    assert args[1] == "new-workspace"


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_ensure_shared_workspace_reuses_live_ref(mock_run, mock_which) -> None:
    mock_run.return_value = _completed(stdout=json.dumps(TREE_FOUND))
    ref = ensure_shared_workspace(existing_ref="workspace:9")
    assert ref == "workspace:9"
    args = mock_run.call_args.args[0]
    assert args[1] == "tree"


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_ensure_shared_workspace_respawns_when_ref_is_dead(mock_run, mock_which) -> None:
    mock_run.side_effect = [
        _completed(returncode=1, stderr="workspace not found"),  # tree check fails
        _completed(stdout="OK workspace:12"),  # new-workspace
    ]
    ref = ensure_shared_workspace(existing_ref="workspace:9")
    assert ref == "workspace:12"


TREE_SPAWN = {
    "windows": [
        {
            "workspaces": [
                {"panes": [{"ref": "pane:21", "surfaces": [{"ref": "surface:37", "title": "shell"}]}]}
            ]
        }
    ]
}


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.time.sleep")
@patch("tq.panes.time.monotonic", side_effect=[0, 1])
@patch("tq.panes.subprocess.run")
def test_launch_agent_in_surface_happy_path(mock_run, mock_monotonic, mock_sleep, mock_which) -> None:
    mock_run.side_effect = [
        _completed(stdout="OK"),  # select-workspace
        _completed(stdout="OK"),  # send
        _completed(stdout="OK"),  # select-workspace (poll)
        _completed(stdout="Claude Code v2.1.205 ready"),  # read-screen
    ]
    launch_agent_in_surface(
        "workspace:9", "surface:37", "/tmp/demo", "/tmp/prompt.md"
    )  # should not raise


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.time.sleep")
@patch("tq.panes.time.monotonic", side_effect=[0, 25])
@patch("tq.panes.subprocess.run")
def test_launch_agent_in_surface_raises_when_launch_never_lands(
    mock_run, mock_monotonic, mock_sleep, mock_which
) -> None:
    mock_run.side_effect = [
        _completed(stdout="OK"),  # select-workspace
        _completed(stdout="OK"),  # send
    ]
    with pytest.raises(C11Unavailable):
        launch_agent_in_surface("workspace:9", "surface:37", "/tmp/demo", "/tmp/prompt.md")


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_bind_project_pane_creates_surface_and_launches(mock_run, mock_which) -> None:
    mock_run.side_effect = [
        _completed(stdout="OK surface:38 pane:21 workspace:9"),  # new-surface
        _completed(stdout="OK"),  # select-workspace (inside launch_agent_in_surface)
        _completed(stdout="OK"),  # send
        _completed(stdout="OK"),  # select-workspace (poll)
        _completed(stdout="Claude Code v2.1.205 ready"),  # read-screen
    ]
    with patch("tq.panes.time.sleep"), patch("tq.panes.time.monotonic", side_effect=[0, 1]):
        workspace_ref, surface_ref = bind_project_pane(
            shared_workspace_ref="workspace:9",
            pane_ref="pane:21",
            directory="/tmp/demo",
            prompt_path="/tmp/prompt.md",
        )
    assert workspace_ref == "workspace:9"
    assert surface_ref == "surface:38"


@patch("tq.panes.shutil.which", return_value=None)
def test_bind_project_pane_raises_when_c11_missing(mock_which) -> None:
    with pytest.raises(C11Unavailable):
        bind_project_pane(
            shared_workspace_ref="workspace:9",
            pane_ref="pane:21",
            directory="/tmp/demo",
            prompt_path="/tmp/prompt.md",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_panes.py -v`
Expected: FAIL with `ImportError: cannot import name 'bind_project_pane' from 'tq.panes'` (none of the new functions exist yet).

- [ ] **Step 3: Rewrite `tq/panes.py`**

Replace the entire file:

```python
"""c11 pane primitives for tq's shared-workspace, tq-recorded-binding model.

Unlike the old cwd-matching discovery, tq now records exactly which
workspace/surface belongs to the orchestrator and to each project (see
Config.orchestrator_workspace_ref / Project.workspace_ref). This module only
provides the primitives to create, verify, and launch into those surfaces --
deciding *when* to (re)bind is the orchestrator's job (the tq-orchestrator
skill).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time


class C11Unavailable(RuntimeError):
    """The c11 CLI is missing, its socket is unreachable, or a call failed."""


def _run_c11_raw(*args: str) -> str:
    """Run `c11 <args>` and return raw stdout text (no --json, no parsing)."""
    if shutil.which("c11") is None:
        raise C11Unavailable("c11 CLI not found on PATH")
    try:
        result = subprocess.run(["c11", *args], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise C11Unavailable(f"c11 {' '.join(args)} timed out") from exc
    if result.returncode != 0:
        raise C11Unavailable(result.stderr.strip() or f"c11 {' '.join(args)} failed")
    return result.stdout


def _run_c11(*args: str) -> dict:
    stdout = _run_c11_raw("--json", *args)
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise C11Unavailable(f"unexpected c11 output: {exc}") from exc


def surface_exists(workspace_ref: str, surface_ref: str) -> bool:
    """True if `surface_ref` is still present in `workspace_ref`'s tree."""
    try:
        tree = _run_c11("tree", "--workspace", workspace_ref, "--no-layout")
    except C11Unavailable:
        return False
    for window in tree.get("windows", []):
        for ws in window.get("workspaces", []):
            for pane in ws.get("panes", []):
                for s in pane.get("surfaces", []):
                    if s.get("ref") == surface_ref:
                        return True
    return False


def _first_pane_ref(tree: dict) -> str | None:
    for window in tree.get("windows", []):
        for ws in window.get("workspaces", []):
            for pane in ws.get("panes", []):
                return pane.get("ref")
    return None


def first_pane_ref(workspace_ref: str) -> str | None:
    """The ref of the first pane in `workspace_ref`, for `new-surface --pane`."""
    tree = _run_c11("tree", "--workspace", workspace_ref, "--no-layout")
    return _first_pane_ref(tree)


def ensure_shared_workspace(existing_ref: str | None) -> str:
    """Return a live shared-workspace ref, creating one if `existing_ref` is
    unset or no longer exists."""
    if existing_ref is not None:
        try:
            tree = _run_c11("tree", "--workspace", existing_ref, "--no-layout")
        except C11Unavailable:
            tree = None
        if tree is not None:
            return existing_ref
    ws_out = _run_c11_raw("new-workspace", "--title", "tq")
    return ws_out.strip().split()[-1]


def create_surface(workspace_ref: str, pane_ref: str) -> str:
    """Add a new tab (surface) to `pane_ref` inside `workspace_ref`. Returns
    the new surface's ref."""
    out = _run_c11_raw(
        "new-surface", "--pane", pane_ref, "--workspace", workspace_ref, "--no-focus"
    )
    # "OK <surface-ref> <pane-ref> <workspace-ref>"
    return out.strip().split()[1]


SPAWN_LAUNCH_TIMEOUT_SECONDS = 20
SPAWN_POLL_INTERVAL_SECONDS = 1.5


def launch_agent_in_surface(
    workspace_ref: str,
    surface_ref: str,
    directory: str,
    prompt_path: str,
    *,
    launch_cmd: str = "claude --dangerously-skip-permissions",
    ready_marker: str = "Claude Code",
) -> None:
    """Launch a one-shot claude agent into an existing surface, verifying the
    launch actually took before returning.

    Reuses the two race-condition workarounds found by hand-testing spawning
    fresh workspaces (task bc8988a3), which apply equally to a freshly
    created surface inside an existing workspace: a just-created surface's
    PTY isn't always live yet, so the launch command can land without
    executing; and polling `read-screen` on a non-selected workspace can
    return a stale snapshot well after the agent actually started. Both are
    handled by re-selecting the workspace before sending and on every poll.
    """
    _run_c11_raw("select-workspace", "--workspace", workspace_ref)
    time.sleep(1.5)

    command = f'cd {directory} && {launch_cmd} "Read {prompt_path} and follow the instructions."'
    _run_c11_raw("send", "--workspace", workspace_ref, "--surface", surface_ref, command)

    deadline = time.monotonic() + SPAWN_LAUNCH_TIMEOUT_SECONDS
    resubmitted = False
    while time.monotonic() < deadline:
        time.sleep(SPAWN_POLL_INTERVAL_SECONDS)
        _run_c11_raw("select-workspace", "--workspace", workspace_ref)
        screen = _run_c11_raw(
            "read-screen", "--workspace", workspace_ref, "--surface", surface_ref, "--lines", "40"
        )
        if ready_marker in screen:
            return
        if not resubmitted and launch_cmd in screen:
            _run_c11_raw("send-key", "--workspace", workspace_ref, "--surface", surface_ref, "enter")
            resubmitted = True

    raise C11Unavailable(
        f"agent launch into {workspace_ref}/{surface_ref} did not land within "
        f"{SPAWN_LAUNCH_TIMEOUT_SECONDS}s"
    )


def bind_project_pane(
    shared_workspace_ref: str, pane_ref: str, directory: str, prompt_path: str
) -> tuple[str, str]:
    """Create a new surface for a project inside the shared workspace and
    launch its first agent. Returns (workspace_ref, surface_ref) to record
    onto the Project."""
    surface_ref = create_surface(shared_workspace_ref, pane_ref)
    launch_agent_in_surface(shared_workspace_ref, surface_ref, directory, prompt_path)
    return shared_workspace_ref, surface_ref


def surface_activity(workspace_ref: str, surface_ref: str) -> str | None:
    """Per-surface derived liveness: 'working' / 'idle' / None if unknown."""
    try:
        meta = _run_c11("get-metadata", "--workspace", workspace_ref, "--surface", surface_ref)
    except C11Unavailable:
        return None
    return meta.get("metadata", {}).get("activity")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_panes.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_panes.py tq/panes.py
git commit -m "Replace live pane discovery with shared-workspace binding primitives"
```

---

### Task 6: Update the CLI — remove `project panes`/`project spawn`, add `ensure-orchestrator`

**Files:**
- Modify: `tq/cli.py`

- [ ] **Step 1: Remove the dead subcommands and their handlers**

In `tq/cli.py`, delete the functions `cmd_project_panes` and `cmd_project_spawn`, and delete their `argparse` wiring (`p_project_panes` and `p_project_spawn` blocks, including the `project_sub.add_parser("panes", ...)` and `project_sub.add_parser("spawn", ...)` calls). Delete the now-unused import:

```python
from tq.panes import C11Unavailable, list_project_workspaces, spawn_background_agent
```

- [ ] **Step 2: Add the `ensure-orchestrator` command**

Add this import at the top of `tq/cli.py`:

```python
from tq.config import ConfigStore
from tq.panes import (
    C11Unavailable,
    bind_project_pane,
    create_surface,
    ensure_shared_workspace,
    first_pane_ref,
    launch_agent_in_surface,
    surface_exists,
)
```

Add this function (near the other `cmd_orchestrator_*` functions):

```python
def cmd_ensure_orchestrator(args: argparse.Namespace) -> None:
    config_store = ConfigStore()
    config = config_store.load()

    if config.orchestrator_workspace_ref and config.orchestrator_surface_ref:
        if surface_exists(config.orchestrator_workspace_ref, config.orchestrator_surface_ref):
            print(
                f"alive: {config.orchestrator_workspace_ref}/{config.orchestrator_surface_ref}"
            )
            return

    shared_ref = ensure_shared_workspace(config.shared_workspace_ref)
    if shared_ref != config.shared_workspace_ref:
        config_store.set_shared_workspace_ref(shared_ref)

    pane_ref = first_pane_ref(shared_ref)
    if pane_ref is None:
        print(f"shared workspace {shared_ref} has no pane to add a surface to", file=sys.stderr)
        sys.exit(1)

    surface_ref = create_surface(shared_ref, pane_ref)
    try:
        launch_agent_in_surface(shared_ref, surface_ref, ".", args.prompt_file)
    except C11Unavailable as exc:
        print(f"orchestrator launch failed: {exc}", file=sys.stderr)
        sys.exit(1)

    config_store.set_orchestrator_pane(shared_ref, surface_ref)
    print(f"spawned: {shared_ref}/{surface_ref}")
```

Add the parser wiring, right after the `p_orch_release` block in `build_parser`:

```python
    p_orch_ensure = orchestrator_sub.add_parser(
        "ensure", help="ensure the orchestrator's pane is alive, spawning it if not"
    )
    p_orch_ensure.add_argument("prompt_file", help="prompt file to launch the orchestrator with")
    p_orch_ensure.set_defaults(func=lambda store, args: cmd_ensure_orchestrator(args))
```

- [ ] **Step 3: Update the module docstring**

Replace the usage docstring at the top of `tq/cli.py`:

```python
"""CLI for agents to read/push/pop the task queue, and for the orchestrator
to bind project panes and manage its own pane.

Usage:
  tq list [--status queued|in_progress|done|dropped] [--project NAME] [--json]
  tq push "<title>" [--notes "<notes>"] [--project NAME]
  tq pop [--project NAME] [--json]
  tq done <id>
  tq drop <id>
  tq start <id>
  tq rm <id>
  tq edit <id> [--title "<title>"] [--notes "<notes>"] [--project NAME]
  tq project add <name> <directory> [--repo <owner/name>] [--create-repo] [--init-dir]
  tq project list [--json]
  tq orchestrator log "<message>"
  tq orchestrator recent [--limit N] [--json]
  tq orchestrator claim <owner> [--json]
  tq orchestrator release <owner>
  tq orchestrator ensure <prompt-file>
"""
```

- [ ] **Step 4: Manually verify the CLI still parses correctly**

Run: `uv run tq list --json`
Expected: `[]` (empty queue on a fresh env, or existing tasks if `TQ_PATH` already has data)

Run: `uv run tq project panes demo 2>&1 | head -5`
Expected: `error: argument project_command: invalid choice: 'panes'` (confirms the dead subcommand is gone)

- [ ] **Step 5: Commit**

```bash
git add tq/cli.py
git commit -m "Remove live pane discovery commands, add orchestrator ensure command"
```

---

### Task 7: Bind-on-delivery CLI support for the orchestrator

The orchestrator (a Claude Code agent following the `tq-orchestrator` skill)
needs one more CLI verb to actually create+bind a project's first pane —
`ensure-orchestrator` covers the orchestrator's own pane, but project pane
binding needs its own command since it takes a project name and a prompt.

**Files:**
- Modify: `tq/cli.py`

- [ ] **Step 1: Add the `project bind` command**

Add this function to `tq/cli.py` (near `cmd_project_add`):

```python
def cmd_project_bind(args: argparse.Namespace) -> None:
    config_store = ConfigStore()
    pstore = ProjectStore()
    project = pstore.get(args.name)
    if project is None:
        print(f"no project named {args.name}", file=sys.stderr)
        sys.exit(1)
    if project.workspace_ref and project.surface_ref:
        print(
            f"already bound: {project.workspace_ref}/{project.surface_ref}", file=sys.stderr
        )
        sys.exit(1)

    config = config_store.load()
    shared_ref = ensure_shared_workspace(config.shared_workspace_ref)
    if shared_ref != config.shared_workspace_ref:
        config_store.set_shared_workspace_ref(shared_ref)

    pane_ref = first_pane_ref(shared_ref)
    if pane_ref is None:
        print(f"shared workspace {shared_ref} has no pane to add a surface to", file=sys.stderr)
        sys.exit(1)

    try:
        workspace_ref, surface_ref = bind_project_pane(
            shared_ref, pane_ref, project.directory, args.prompt_file
        )
    except C11Unavailable as exc:
        print(f"bind failed: {exc}", file=sys.stderr)
        sys.exit(1)

    pstore.bind(args.name, workspace_ref, surface_ref)
    print(f"bound {args.name} -> {workspace_ref}/{surface_ref}")
```

Add the parser wiring, right after the `p_project_add` block:

```python
    p_project_bind = project_sub.add_parser(
        "bind", help="create a pane for a project in the shared workspace and launch its first agent"
    )
    p_project_bind.add_argument("name")
    p_project_bind.add_argument("prompt_file", help="prompt file for the project's first task")
    p_project_bind.set_defaults(func=lambda store, args: cmd_project_bind(args))
```

- [ ] **Step 2: Manually verify the command is wired up**

Run: `uv run tq project bind nonexistent /tmp/prompt.md`
Expected: `no project named nonexistent` on stderr, exit code 1

- [ ] **Step 3: Commit**

```bash
git add tq/cli.py
git commit -m "Add project bind command for orchestrator-driven pane creation"
```

---

### Task 8: Rewrite the orchestrator skill

**Files:**
- Create: `skills/tq-orchestrator/SKILL.md`
- Delete: `skills/orchestrator-loop/SKILL.md` (git mv + rewrite, not a fresh file)

- [ ] **Step 1: Move and rewrite the skill file**

```bash
git mv skills/orchestrator-loop skills/tq-orchestrator
git mv skills/tq-orchestrator/SKILL.md skills/tq-orchestrator/SKILL.md.bak  # keep for reference during rewrite, remove in step 3
```

- [ ] **Step 2: Write the new `skills/tq-orchestrator/SKILL.md`**

```markdown
---
name: tq-orchestrator
description: Use when you are the persistent tq orchestrator agent, nudged by a cron cadence to check the tq task queue — triage unassigned tasks, deliver work by pushing it directly into project panes, drive obvious in-flight decisions in project panes, and escalate anything ambiguous or consequential to the user.
---

# tq Orchestrator

You are a **persistent** agent — the same pane runs across every cron nudge,
so your conversation history and context carry over turn to turn. A cron
sends `"check tq now"` into your pane on a schedule; this skill is what you
do each time you're nudged.

## Cycle

1. **Check the queue**: `tq list --json`. Any `queued` items are new or
   still-undelivered work.

2. **Triage unassigned tasks.** For every `queued` task with `project:
   null`, read its title/notes and judge against `tq project list --json`:
   - **Matches an existing project** → `tq edit <id> --project <name>`.
     Leave it `queued` — delivery happens in step 3, this cycle or a later
     one.
   - **Explicitly needs a brand-new project** — the task's own text says so
     in plain language ("new repo for this", "spin up a fresh project for
     X"). A task merely lacking a project match is NOT enough justification
     on its own — see the ambiguous case below.
     1. Pick a project name and local directory (default
        `~/workplace/<name>`).
     2. `tq project add <name> <dir> --init-dir` — add `--repo
        <owner/name> --create-repo` only if the task text implies
        GitHub-backed; otherwise local-only.
     3. `tq edit <id> --project <name>`.
   - **Ambiguous** — you cannot confidently place it in either bucket above
     → leave it `queued` and unassigned, and escalate to the user (step 5)
     rather than guess. Do not create a project speculatively.

3. **Deliver assigned, queued work.** For every `queued` task with a
   non-null `project`:
   - **No pane bound yet** (`tq project list --json` shows null
     `workspace_ref`/`surface_ref` for that project) → write the task's
     title+notes to a prompt file, then `tq project bind <name>
     <prompt-file>`. This creates the project's pane inside the shared
     workspace and hands it the task as its first prompt in one step — the
     new session owns the task immediately. Mark the task `in_progress`
     (`tq start <id>`) once the bind call succeeds.
   - **Already bound** → check whether the bound surface is idle before
     sending anything (see "Checking a pane's state" below).
     - **Idle** → `c11 send --workspace <ws> --surface <s> "<title + notes>"`,
       then `tq start <id>`, then log a breadcrumb (step 6).
     - **Working** → leave the task `queued`; you'll retry next cycle.
   - Do not deliver more than one task to the same pane per cycle — one
     `in_progress` task per pane is the invariant; wait for it to finish
     before sending the next.

4. **Drive obvious in-flight decisions.** For every project pane currently
   showing a waiting-on-input state (`c11 read-screen` on that surface), read
   what it's asking:
   - **It names a recommended option** ("I'd recommend X — proceed?", a
     numbered list with one marked "(recommended)") → drive it forward
     yourself: `c11 send` confirming the recommended option. No escalation —
     this is exactly as unambiguous as a yes/no continuation.
   - **No clear recommendation, or real architectural/consequential
     stakes** (which of several genuinely different options, anything with
     real consequences or unclear intent) → leave it alone, escalate to the
     user (step 5). Do not decide for them.

5. **Escalate what you can't resolve.** Anything ambiguous from step 2, or
   a hard decision from step 4 — summarize it and ping the user. Don't
   guess on real consequences.

6. **Log a breadcrumb**: `tq orchestrator log "<short summary>"` — what you
   triaged, delivered, drove, or escalated this cycle. Keep it terse; this
   is what the tq TUI surfaces to the human without them switching to your
   pane.

## Checking a pane's state

A project's bound surface's per-surface derived liveness is exposed via
`c11 get-metadata --workspace <ws> --surface <s>` — look at
`metadata.activity`, which is `"working"` or `"idle"`. This is genuinely
per-surface (unlike `c11 list-status`, which aggregates per *workspace* and
will never report a decisive `Idle` once more than one Claude Code surface
shares a workspace — exactly the situation here, since every project pane
lives in the same shared workspace as you). Always use `get-metadata`, never
`list-status`, when checking a project pane's state.

`activity: "idle"` is a strong signal but not proof for a pane mid-decision
(step 4) — confirm with `c11 read-screen` before treating a decision as
resolved or unresolved.

## Rebinding a stale pane

If `tq project bind` or a `c11 send` into a recorded surface fails because
the surface no longer exists (closed, workspace gone), clear the stale
binding — there's no `tq project unbind` command; ask the user if this
happens, since a silently-lost pane binding likely means something closed
unexpectedly and is worth a human noticing, not silently re-spawning around.

## Useful commands

```
tq list --json                                  # current queue state
tq push "<title>" [--notes "..."] [--project demo]
tq edit <id> --project <name>
tq start <id> / done <id> / drop <id>
tq project list --json                          # includes workspace_ref/surface_ref per project
tq project add <name> <dir> --init-dir [--repo <owner/name> --create-repo]
tq project bind <name> <prompt-file>            # create pane + deliver first task
tq orchestrator log "<message>"
tq orchestrator ensure <prompt-file>             # not called by you — the TUI/cron call this to keep you alive

c11 get-metadata --workspace <w> --surface <s>   # per-surface activity
c11 read-screen --workspace <w> --surface <s>    # tail a pane's output
c11 send --workspace <w> --surface <s> "<text>"  # push text + Enter into a pane
```
```

- [ ] **Step 3: Remove the backup file**

```bash
rm skills/tq-orchestrator/SKILL.md.bak
```

- [ ] **Step 4: Commit**

```bash
git add -A skills/
git commit -m "Rewrite orchestrator-loop skill as tq-orchestrator for the persistent/push model"
```

---

### Task 9: Update the TUI — Projects view gains pane info, Queue view gains orchestrator health

**Files:**
- Modify: `tq/tui.py`

- [ ] **Step 1: Add an orchestrator health helper**

At the top of `tq/tui.py`, after the existing imports, add:

```python
from tq.panes import surface_activity, surface_exists
```

Add this method to `ExpQueueApp` (rename the class in the same edit — see Step 4), right after `__init__`:

```python
    def _orchestrator_health(self) -> str:
        config = self.config_store.load()
        ws = config.orchestrator_workspace_ref
        surf = config.orchestrator_surface_ref
        if not ws or not surf:
            return "orchestrator: not set up"
        if not surface_exists(ws, surf):
            return "orchestrator: not running"
        activity = surface_activity(ws, surf) or "unknown"
        return f"orchestrator: ● {activity} ({ws}/{surf})"
```

- [ ] **Step 2: Wire the health line into the Queue view's existing status bar**

Find `refresh_orchestrator_panel` in `tq/tui.py` and change it to prepend the health line:

```python
    def refresh_orchestrator_panel(self) -> None:
        panel = self.query_one("#orchestrator-panel", Static)
        events = self.orchestrator_store.recent(limit=5)
        lines = [self._orchestrator_health(), ""]
        if not events:
            lines.append("(no activity logged)")
        else:
            lines.append("recent activity:")
            for e in events:
                when = time.strftime("%H:%M:%S", time.localtime(e.ts))
                lines.append(f"  [{when}] {e.message}")
        panel.update("\n".join(lines))
```

- [ ] **Step 3: Add pane-binding columns to the Projects view**

Find `refresh_projects_view` in `tq/tui.py` and change the columns and row data:

```python
    def refresh_projects_view(self) -> None:
        table = self.query_one("#projects-table", DataTable)
        selected_key = None
        if table.row_count and table.cursor_coordinate is not None:
            try:
                row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
                selected_key = row_key.value
            except Exception:
                selected_key = None

        table.clear(columns=True)
        table.add_columns("name", "directory", "repo", "pane", "status")
        for p in self.project_store.list():
            kind = p.repo or "(local)"
            if p.workspace_ref and p.surface_ref:
                pane = f"{p.workspace_ref}/{p.surface_ref}"
                status = surface_activity(p.workspace_ref, p.surface_ref) or "unknown"
                if not surface_exists(p.workspace_ref, p.surface_ref):
                    status = "gone"
            else:
                pane = "(unbound)"
                status = "-"
            table.add_row(p.name, p.directory, kind, pane, status, key=p.name)

        if selected_key:
            for row_index in range(table.row_count):
                row_key = table.coordinate_to_cell_key((row_index, 0))[0]
                if row_key.value == selected_key:
                    table.move_cursor(row=row_index)
                    break
```

- [ ] **Step 4: Rename the app class and module references from expqueue to tq**

In `tq/tui.py`:
- Rename `class ExpQueueApp(App):` to `class TqApp(App):`.
- Update `TITLE = "Experiment Queue"` to `TITLE = "tq"`.
- Update the module-level docstring's references from `expqueue`-specific wording to `tq` (mechanical text edit, same structure).
- Update `def main() -> None: ExpQueueApp().run()` to `def main() -> None: TqApp().run()`.

- [ ] **Step 5: Manually verify the TUI still launches and shows the new columns**

Run: `uv run tq-tui`
Expected: App launches; Queue view shows `orchestrator: not set up` (or `not running`/`● idle`/`● working` if `orchestrator ensure` has been run) at the top of the bottom panel; pressing `2` shows the Projects view with `pane` and `status` columns populated per registered project. Quit with `q`.

- [ ] **Step 6: Commit**

```bash
git add tq/tui.py
git commit -m "Surface orchestrator health and pane bindings in the TUI"
```

---

### Task 10: Remove the now-dead `pop`-as-delivery documentation, update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite `README.md`**

Replace the entire file:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Rewrite README for tq's persistent-orchestrator, push-delivery model"
```

---

### Task 11: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: All tests pass — `test_config.py`, `test_orchestrator.py`,
`test_panes.py`, `test_projects.py`, `test_store.py`.

- [ ] **Step 2: Grep for any leftover `expqueue` references**

Run: `grep -ril expqueue . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ --exclude-dir=.superpowers`
Expected: no output (or only historical references inside
`docs/superpowers/plans/2026-07-15-*.md` and
`docs/superpowers/specs/2026-07-15-*.md`, which document the *prior* design
and should stay as historical record, not be edited).

- [ ] **Step 3: Manually smoke-test the orchestrator ensure + project bind flow**

This requires a running c11 app (already the case in this environment).

```bash
export TQ_PATH=/tmp/tq-smoke/queue.json
export TQ_PROJECTS_PATH=/tmp/tq-smoke/projects.json
export TQ_CONFIG_PATH=/tmp/tq-smoke/config.json
export TQ_ORCHESTRATOR_PATH=/tmp/tq-smoke/orchestrator.json

uv run tq project add smoketest /tmp/tq-smoke/proj --init-dir
echo "Say hello and then exit." > /tmp/tq-smoke-prompt.md
uv run tq project bind smoketest /tmp/tq-smoke-prompt.md
```

Expected: prints `bound smoketest -> workspace:N/surface:M`; a new c11 tab
appears with a claude session that received the prompt. Confirm with:

```bash
uv run tq project list --json
```

Expected: the `smoketest` project's JSON shows non-null `workspace_ref`/
`surface_ref` matching what was printed.

Clean up the smoke-test c11 pane and temp files afterward:

```bash
rm -rf /tmp/tq-smoke /tmp/tq-smoke-prompt.md
```

(Close the spawned c11 tab manually, or `c11 close-surface --surface <ref>`
using the ref printed above.)

- [ ] **Step 4: No commit for this task** — verification only, nothing to add.

---

## Post-plan note

This plan does not set up the actual cron (`/loop`) invocation that nudges
the orchestrator — that's an operator action (running `/loop 5m "check tq
now" <target-surface>` or equivalent against the live orchestrator pane
after Task 6/8 land), not a code change, and depends on the user's specific
cron/loop tooling already present in this environment. Do it manually after
this plan is merged, following the `tq-orchestrator` skill's own
instructions for what the nudge should say.
