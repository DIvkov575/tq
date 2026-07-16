"""Textual TUI for tq.

Two views, switchable with 1/2 or Tab:
  1  Queue view    - tasks grouped into RUNNING / QUEUED / COMPLETED sections,
                     plus orchestrator health + a recent-activity panel
  2  Projects view - registered projects: name, directory, repo, bound
                     pane, and that pane's live status

Queue view keybindings:
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

Global:
  1 / 2     jump to Queue / Projects view
  Tab       cycle to the next view
  q         quit
"""

from __future__ import annotations

import time

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static

from tq.config import ConfigStore
from tq.orchestrator import OrchestratorStore
from tq.panes import surface_activity, surface_exists
from tq.projects import ProjectStore
from tq.store import QueueStore, STATUSES, Task

STATUS_ICON = {
    "queued": "⏳",
    "in_progress": "▶",
    "done": "✔",
    "dropped": "✘",
}

FILTER_CYCLE = [None, *STATUSES]

# Visual grouping order: active work first, then queued, then finished.
# "done" and "dropped" share one "completed" section since both are terminal.
SECTION_ORDER = ["in_progress", "queued", "completed"]
SECTION_LABEL = {
    "in_progress": "RUNNING",
    "queued": "QUEUED",
    "completed": "COMPLETED",
}

UNASSIGNED = "(unassigned)"

VIEWS = ["queue", "projects"]
VIEW_LABEL = {"queue": "Queue", "projects": "Projects"}


def _section_of(status: str) -> str:
    if status in ("done", "dropped"):
        return "completed"
    return status


class InputModal(ModalScreen[str | None]):
    """Simple modal that collects a line of text."""

    DEFAULT_CSS = """
    InputModal {
        align: center middle;
    }
    #dialog {
        width: 60%;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, prompt: str, initial: str = ""):
        super().__init__()
        self.prompt = prompt
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.prompt)
            yield Input(value=self.initial, id="modal-input")

    def on_mount(self) -> None:
        self.query_one("#modal-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class TqApp(App):
    TITLE = "tq"

    CSS = """
    Screen {
        layout: vertical;
    }
    #view-bar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    #status-bar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    #orchestrator-panel {
        height: auto;
        max-height: 8;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
        border-top: solid $accent;
    }
    """

    BINDINGS = [
        Binding("1", "goto_queue", "Queue"),
        Binding("2", "goto_projects", "Projects"),
        Binding("tab", "cycle_view", "Next view", priority=True),
        Binding("a", "add_task", "Add"),
        Binding("e", "edit_task", "Edit"),
        Binding("d", "mark_done", "Done"),
        Binding("x", "mark_dropped", "Drop"),
        Binding("s", "mark_started", "Start"),
        Binding("r", "requeue", "Requeue"),
        Binding("p", "assign_project", "Project"),
        Binding("D", "delete_task", "Delete", key_display="shift+d"),
        Binding("/", "cycle_filter", "Filter"),
        Binding("q", "quit", "Quit"),
    ]

    filter_status: reactive[str | None] = reactive(None, init=False)
    active_view: reactive[str] = reactive("queue", init=False)

    def __init__(self):
        super().__init__()
        self.store = QueueStore()
        self.project_store = ProjectStore()
        self.config_store = ConfigStore()
        self.orchestrator_store = OrchestratorStore()
        self._rows: list[Task] = []
        self._header_keys: set[str] = set()

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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._view_bar_text(), id="view-bar")
        yield Static("filter: all", id="status-bar")
        yield DataTable(id="queue-table", cursor_type="row", zebra_stripes=True)
        yield DataTable(id="projects-table", cursor_type="row", zebra_stripes=True)
        yield Static(id="orchestrator-panel")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_view_visibility()
        self.refresh_all()
        self.set_interval(2.0, self.refresh_all)

    def refresh_all(self) -> None:
        self.refresh_table()
        self.refresh_projects_view()
        self.refresh_orchestrator_panel()

    # -- view switching ---------------------------------------------------

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
        projects_table = self.query_one("#projects-table", DataTable)
        status_bar = self.query_one("#status-bar", Static)
        orchestrator_panel = self.query_one("#orchestrator-panel", Static)

        queue_table.display = self.active_view == "queue"
        status_bar.display = self.active_view == "queue"
        orchestrator_panel.display = self.active_view == "queue"
        projects_table.display = self.active_view == "projects"

        bar = self.query_one("#view-bar", Static)
        bar.update(self._view_bar_text())

        if self.active_view == "queue":
            self.set_focus(queue_table)
        elif self.active_view == "projects":
            self.set_focus(projects_table)

    def watch_active_view(self, value: str) -> None:
        self._apply_view_visibility()
        self.refresh_all()

    def action_goto_queue(self) -> None:
        self.active_view = "queue"

    def action_goto_projects(self) -> None:
        self.active_view = "projects"

    def action_cycle_view(self) -> None:
        idx = VIEWS.index(self.active_view)
        self.active_view = VIEWS[(idx + 1) % len(VIEWS)]

    # -- queue view -----------------------------------------------------

    def refresh_table(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        selected_id = self._selected_id()
        table.clear(columns=True)
        table.add_columns("", "id", "title", "notes", "status", "project")
        self._rows = self.store.list(status=self.filter_status)

        grouped: dict[str, list[Task]] = {name: [] for name in SECTION_ORDER}
        for t in self._rows:
            grouped[_section_of(t.status)].append(t)

        self._header_keys = set()
        for section in SECTION_ORDER:
            tasks = grouped[section]
            if not tasks:
                continue
            header_key = f"__section_{section}__"
            self._header_keys.add(header_key)
            label = Text(f"── {SECTION_LABEL[section]} ({len(tasks)}) ──", style="bold dim")
            table.add_row("", "", label, "", "", "", key=header_key)
            for t in tasks:
                table.add_row(
                    STATUS_ICON.get(t.status, "?"),
                    t.id,
                    t.title,
                    t.notes,
                    t.status,
                    t.project or UNASSIGNED,
                    key=t.id,
                )

        if selected_id:
            for row_index in range(table.row_count):
                row_key = table.coordinate_to_cell_key((row_index, 0))[0]
                if row_key.value == selected_id:
                    table.move_cursor(row=row_index)
                    break

    def _selected_id(self) -> str | None:
        table = self.query_one("#queue-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            value = row_key.value
        except Exception:
            return None
        if value in self._header_keys:
            return None
        return value

    def watch_filter_status(self, value: str | None) -> None:
        bar = self.query_one("#status-bar", Static)
        bar.update(f"filter: {value or 'all'}")
        self.refresh_table()

    def action_cycle_filter(self) -> None:
        if self.active_view != "queue":
            return
        idx = FILTER_CYCLE.index(self.filter_status)
        self.filter_status = FILTER_CYCLE[(idx + 1) % len(FILTER_CYCLE)]

    def action_add_task(self) -> None:
        if self.active_view != "queue":
            return

        def _on_title(title: str | None) -> None:
            if not title:
                return
            self.store.push(title, project=self.config_store.load().default_project)
            self.refresh_table()

        self.push_screen(InputModal("New task title:"), _on_title)

    def action_edit_task(self) -> None:
        if self.active_view != "queue":
            return
        task_id = self._selected_id()
        if not task_id:
            return
        current = next((t for t in self._rows if t.id == task_id), None)
        if not current:
            return

        def _on_title(title: str | None) -> None:
            if title is None:
                return
            self.store.edit(task_id, title=title)
            self.refresh_table()

        self.push_screen(InputModal("Edit title:", initial=current.title), _on_title)

    def action_mark_done(self) -> None:
        if self.active_view != "queue":
            return
        task_id = self._selected_id()
        if task_id:
            self.store.update_status(task_id, "done")
            self.refresh_table()

    def action_mark_dropped(self) -> None:
        if self.active_view != "queue":
            return
        task_id = self._selected_id()
        if task_id:
            self.store.update_status(task_id, "dropped")
            self.refresh_table()

    def action_mark_started(self) -> None:
        if self.active_view != "queue":
            return
        task_id = self._selected_id()
        if task_id:
            self.store.update_status(task_id, "in_progress")
            self.refresh_table()

    def action_requeue(self) -> None:
        if self.active_view != "queue":
            return
        task_id = self._selected_id()
        if task_id:
            self.store.update_status(task_id, "queued")
            self.refresh_table()

    def action_assign_project(self) -> None:
        if self.active_view != "queue":
            return
        task_id = self._selected_id()
        if not task_id:
            return
        current = next((t for t in self._rows if t.id == task_id), None)
        if not current:
            return
        names = [p.name for p in self.project_store.list()]
        hint = f" (known: {', '.join(names)}, blank = unassigned)" if names else " (blank = unassigned)"

        def _on_project(name: str | None) -> None:
            if name is None:
                return
            self.store.edit(task_id, project=name)
            self.refresh_table()

        self.push_screen(
            InputModal(f"Project name{hint}:", initial=current.project or ""), _on_project
        )

    def action_delete_task(self) -> None:
        if self.active_view != "queue":
            return
        task_id = self._selected_id()
        if task_id:
            self.store.remove(task_id)
            self.refresh_table()

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

    # -- projects view ----------------------------------------------------

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


def main() -> None:
    TqApp().run()


if __name__ == "__main__":
    main()
