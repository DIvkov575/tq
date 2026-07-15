"""File-backed, user-editable settings for expqueue.

This is distinct from the queue/project *data* files: it holds small
preferences (currently just a default project for new tasks) that the TUI's
config view can show and edit live. Queue/project storage paths themselves
are controlled by the EXPQUEUE_PATH / EXPQUEUE_PROJECTS_PATH env vars and are
surfaced read-only in the config view.
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("EXPQUEUE_CONFIG_PATH", Path.home() / "workplace" / ".expqueue" / "config.json")
)


@dataclass
class Config:
    default_project: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Config":
        return Config(default_project=d.get("default_project"))


class ConfigStore:
    def __init__(self, path: Path = DEFAULT_CONFIG_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_raw(Config().to_dict())

    @contextmanager
    def _locked(self):
        lock_path = self.path.with_suffix(".lock")
        lock_fh = open(lock_path, "a+")
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            lock_fh.close()

    def _read_raw(self) -> dict:
        if not self.path.exists():
            return {}
        text = self.path.read_text().strip()
        if not text:
            return {}
        return json.loads(text)

    def _write_raw(self, data: dict) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.replace(self.path)

    def load(self) -> Config:
        with self._locked():
            return Config.from_dict(self._read_raw())

    def set_default_project(self, project: str | None) -> Config:
        with self._locked():
            data = self._read_raw()
            data["default_project"] = project or None
            self._write_raw(data)
            return Config.from_dict(data)
