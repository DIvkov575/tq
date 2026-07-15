"""File-backed experiment queue storage.

Tasks live in a single JSON file, guarded by an flock-based file lock so the
TUI and CLI (used by agents) can safely read/push/pop concurrently.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_QUEUE_PATH = Path(
    os.environ.get("EXPQUEUE_PATH", Path.home() / "workplace" / ".expqueue" / "queue.json")
)

STATUSES = ("queued", "in_progress", "done", "dropped")


@dataclass
class Task:
    id: str
    title: str
    notes: str = ""
    status: str = "queued"
    project: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Task":
        return Task(
            id=d["id"],
            title=d["title"],
            notes=d.get("notes", ""),
            status=d.get("status", "queued"),
            project=d.get("project"),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


class QueueStore:
    def __init__(self, path: Path = DEFAULT_QUEUE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_raw([])

    @contextmanager
    def _locked(self):
        # Lock file separate from data file so we can hold the lock across
        # a read-modify-write cycle without truncating early.
        lock_path = self.path.with_suffix(".lock")
        lock_fh = open(lock_path, "a+")
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            lock_fh.close()

    def _read_raw(self) -> list[dict]:
        if not self.path.exists():
            return []
        text = self.path.read_text().strip()
        if not text:
            return []
        return json.loads(text)

    def _write_raw(self, items: list[dict]) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(items, indent=2))
        tmp_path.replace(self.path)

    def list(self, status: str | None = None) -> list[Task]:
        with self._locked():
            items = [Task.from_dict(d) for d in self._read_raw()]
        if status:
            items = [t for t in items if t.status == status]
        return items

    def push(self, title: str, notes: str = "", project: str | None = None) -> Task:
        task = Task(id=uuid.uuid4().hex[:8], title=title, notes=notes, project=project)
        with self._locked():
            items = self._read_raw()
            items.append(task.to_dict())
            self._write_raw(items)
        return task

    def pop(self, project: str | None = None) -> Task | None:
        """Pop the oldest queued task (FIFO) and mark it in_progress.

        If `project` is given, only considers tasks assigned to that project.
        """
        with self._locked():
            items = self._read_raw()
            for d in items:
                if d.get("status") != "queued":
                    continue
                if project is not None and d.get("project") != project:
                    continue
                d["status"] = "in_progress"
                d["updated_at"] = time.time()
                self._write_raw(items)
                return Task.from_dict(d)
        return None

    def update_status(self, task_id: str, status: str) -> Task | None:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        with self._locked():
            items = self._read_raw()
            for d in items:
                if d["id"] == task_id:
                    d["status"] = status
                    d["updated_at"] = time.time()
                    self._write_raw(items)
                    return Task.from_dict(d)
        return None

    def remove(self, task_id: str) -> bool:
        with self._locked():
            items = self._read_raw()
            new_items = [d for d in items if d["id"] != task_id]
            changed = len(new_items) != len(items)
            if changed:
                self._write_raw(new_items)
        return changed

    def edit(
        self,
        task_id: str,
        title: str | None = None,
        notes: str | None = None,
        project: str | None = None,
    ) -> Task | None:
        with self._locked():
            items = self._read_raw()
            for d in items:
                if d["id"] == task_id:
                    if title is not None:
                        d["title"] = title
                    if notes is not None:
                        d["notes"] = notes
                    if project is not None:
                        d["project"] = project or None
                    d["updated_at"] = time.time()
                    self._write_raw(items)
                    return Task.from_dict(d)
        return None
