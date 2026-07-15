"""Textual TUI for the experiment queue.

Keybindings:
  a         add a new task
  e         edit selected task's title
  d         mark selected task done
  x         drop selected task
  s         mark selected task in_progress ("start")
  r         requeue selected task (back to queued)
  p         assign selected task to a project
  D         delete selected task
  /         filter by status (cycles: all -> queued -> in_progress -> done -> dropped)
  q         quit
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static

from expqueue.projects import ProjectStore
from expqueue.store import QueueStore, STATUSES, Task

STATUS_ICON = {
    "queued": "⏳",
    "in_progress": "▶",
    "done": "✔",
    "dropped": "✘",
}

FILTER_CYCLE = [None, *STATUSES]


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
    #status-bar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
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

    def __init__(self):
        super().__init__()
        self.store = QueueStore()
        self.project_store = ProjectStore()
        self._rows: list[Task] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("filter: all", id="status-bar")
        yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_table()
        self.set_interval(2.0, self.refresh_table)

    def refresh_table(self) -> None:
        table = self.query_one(DataTable)
        selected_id = self._selected_id()
        table.clear(columns=True)
        table.add_columns("", "id", "title", "notes", "status", "project")
        self._rows = self.store.list(status=self.filter_status)
        for t in self._rows:
            table.add_row(
                STATUS_ICON.get(t.status, "?"),
                t.id,
                t.title,
                t.notes,
                t.status,
                t.project or "",
                key=t.id,
            )
        if selected_id:
            for row_index, t in enumerate(self._rows):
                if t.id == selected_id:
                    table.move_cursor(row=row_index)
                    break

    def _selected_id(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            return row_key.value
        except Exception:
            return None

    def watch_filter_status(self, value: str | None) -> None:
        bar = self.query_one("#status-bar", Static)
        bar.update(f"filter: {value or 'all'}")
        self.refresh_table()

    def action_cycle_filter(self) -> None:
        idx = FILTER_CYCLE.index(self.filter_status)
        self.filter_status = FILTER_CYCLE[(idx + 1) % len(FILTER_CYCLE)]

    def action_add_task(self) -> None:
        def _on_title(title: str | None) -> None:
            if not title:
                return
            self.store.push(title)
            self.refresh_table()

        self.push_screen(InputModal("New task title:"), _on_title)

    def action_edit_task(self) -> None:
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
        task_id = self._selected_id()
        if task_id:
            self.store.update_status(task_id, "done")
            self.refresh_table()

    def action_mark_dropped(self) -> None:
        task_id = self._selected_id()
        if task_id:
            self.store.update_status(task_id, "dropped")
            self.refresh_table()

    def action_mark_started(self) -> None:
        task_id = self._selected_id()
        if task_id:
            self.store.update_status(task_id, "in_progress")
            self.refresh_table()

    def action_requeue(self) -> None:
        task_id = self._selected_id()
        if task_id:
            self.store.update_status(task_id, "queued")
            self.refresh_table()

    def action_assign_project(self) -> None:
        task_id = self._selected_id()
        if not task_id:
            return
        current = next((t for t in self._rows if t.id == task_id), None)
        if not current:
            return
        names = [p.name for p in self.project_store.list()]
        hint = f" (known: {', '.join(names)})" if names else ""

        def _on_project(name: str | None) -> None:
            if name is None:
                return
            self.store.edit(task_id, project=name)
            self.refresh_table()

        self.push_screen(
            InputModal(f"Project name{hint}:", initial=current.project or ""), _on_project
        )

    def action_delete_task(self) -> None:
        task_id = self._selected_id()
        if task_id:
            self.store.remove(task_id)
            self.refresh_table()


def main() -> None:
    ExpQueueApp().run()


if __name__ == "__main__":
    main()
