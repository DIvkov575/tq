"""Textual TUI for the experiment queue.

Views (switch with 1/2/3, or Tab to cycle):
  1  Queue view  - tasks grouped into RUNNING / QUEUED / COMPLETED sections
  2  State view  - per-project dashboard: task counts, last status, last touched
  3  Config view - current paths + editable default project

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

Config view keybindings:
  e         edit the default project used for new tasks

Global:
  1 / 2 / 3   jump to Queue / State / Config view
  Tab         cycle to the next view
  q           quit
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

from expqueue.config import ConfigStore
from expqueue.projects import ProjectStore
from expqueue.store import QueueStore, STATUSES, Task

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

VIEWS = ["queue", "state", "config"]
VIEW_LABEL = {"queue": "Queue", "state": "State", "config": "Config"}

UNASSIGNED = "(unassigned)"


def _section_of(status: str) -> str:
    if status in ("done", "dropped"):
        return "completed"
    return status


def _relative_time(ts: float) -> str:
    delta = max(0, time.time() - ts)
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


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


class ExpQueueApp(App):
    TITLE = "Experiment Queue"

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
    #config-body {
        padding: 1 2;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("1", "goto_queue", "Queue"),
        Binding("2", "goto_state", "State"),
        Binding("3", "goto_config", "Config"),
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
        self._rows: list[Task] = []
        self._header_keys: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._view_bar_text(), id="view-bar")
        yield Static("filter: all", id="status-bar")
        yield DataTable(id="queue-table", cursor_type="row", zebra_stripes=True)
        yield DataTable(id="state-table", cursor_type="row", zebra_stripes=True)
        with Vertical(id="config-body"):
            yield Static(id="config-text")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_view_visibility()
        self.refresh_all()
        self.set_interval(2.0, self.refresh_all)

    def refresh_all(self) -> None:
        self.refresh_table()
        self.refresh_state_view()
        self.refresh_config_view()

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
        if self.active_view == "config":
            self._edit_default_project()
            return
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


def main() -> None:
    ExpQueueApp().run()


if __name__ == "__main__":
    main()
