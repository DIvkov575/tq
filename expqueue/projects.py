"""File-backed project registry.

Projects live in a single JSON file next to the queue, guarded by the same
flock pattern as QueueStore. Each project has a name, an optional GitHub repo
(created via `gh` if it doesn't exist yet), and an associated local directory.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PROJECTS_PATH = Path(
    os.environ.get(
        "EXPQUEUE_PROJECTS_PATH",
        Path.home() / "workplace" / ".expqueue" / "projects.json",
    )
)


@dataclass
class Project:
    name: str
    directory: str
    repo: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Project":
        return Project(
            name=d["name"],
            directory=d["directory"],
            repo=d.get("repo"),
            created_at=d.get("created_at", time.time()),
        )


class ProjectStore:
    def __init__(self, path: Path = DEFAULT_PROJECTS_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_raw([])

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

    def list(self) -> list[Project]:
        with self._locked():
            return [Project.from_dict(d) for d in self._read_raw()]

    def get(self, name: str) -> Project | None:
        for p in self.list():
            if p.name == name:
                return p
        return None

    def add(self, name: str, directory: str, repo: str | None = None) -> Project:
        project = Project(name=name, directory=str(Path(directory).expanduser()), repo=repo)
        with self._locked():
            items = self._read_raw()
            if any(d["name"] == name for d in items):
                raise ValueError(f"project already exists: {name}")
            items.append(project.to_dict())
            self._write_raw(items)
        return project


def ensure_gh_repo(repo: str) -> bool:
    """Create `repo` on GitHub via `gh repo create` if it doesn't already exist.

    `repo` may be "name" or "owner/name". Returns True if a repo was created,
    False if it already existed. Raises RuntimeError if `gh` is unavailable
    or the create call fails.
    """
    check = subprocess.run(
        ["gh", "repo", "view", repo], capture_output=True, text=True
    )
    if check.returncode == 0:
        return False
    create = subprocess.run(
        ["gh", "repo", "create", repo, "--private", "--confirm"],
        capture_output=True,
        text=True,
    )
    if create.returncode != 0:
        raise RuntimeError(f"gh repo create failed: {create.stderr.strip()}")
    return True
