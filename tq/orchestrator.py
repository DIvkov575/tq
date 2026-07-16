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

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_ORCHESTRATOR_PATH = Path(
    os.environ.get(
        "TQ_ORCHESTRATOR_PATH",
        Path.home() / "workplace" / ".tq" / "orchestrator.json",
    )
)

MAX_EVENTS = 20
CLAIM_TTL_SECONDS = 60  # a claim older than this is treated as abandoned


@dataclass
class OrchestratorEvent:
    message: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "OrchestratorEvent":
        return OrchestratorEvent(message=d["message"], ts=d.get("ts", time.time()))


class OrchestratorStore:
    def __init__(self, path: Path = DEFAULT_ORCHESTRATOR_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_raw({"events": [], "claim": None})

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
            return {"events": [], "claim": None}
        text = self.path.read_text().strip()
        if not text:
            return {"events": [], "claim": None}
        data = json.loads(text)
        data.setdefault("events", [])
        data.setdefault("claim", None)
        return data

    def _write_raw(self, data: dict) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.replace(self.path)

    def log(self, message: str) -> OrchestratorEvent:
        event = OrchestratorEvent(message=message)
        with self._locked():
            data = self._read_raw()
            data["events"].append(event.to_dict())
            data["events"] = data["events"][-MAX_EVENTS:]
            self._write_raw(data)
        return event

    def recent(self, limit: int = 5) -> list[OrchestratorEvent]:
        """Most recent events first."""
        with self._locked():
            data = self._read_raw()
        events = [OrchestratorEvent.from_dict(d) for d in data["events"]]
        return list(reversed(events))[:limit]

    def claim(self, owner: str) -> bool:
        """Attempt the singleton run slot. Returns False if another owner
        holds a non-stale claim; re-claiming as the same owner always
        succeeds (acts as a heartbeat refresh)."""
        now = time.time()
        with self._locked():
            data = self._read_raw()
            current = data.get("claim")
            if (
                current
                and current.get("owner") != owner
                and now - current.get("ts", 0) < CLAIM_TTL_SECONDS
            ):
                return False
            data["claim"] = {"owner": owner, "ts": now}
            self._write_raw(data)
            return True

    def release(self, owner: str) -> None:
        with self._locked():
            data = self._read_raw()
            current = data.get("claim")
            if current and current.get("owner") == owner:
                data["claim"] = None
                self._write_raw(data)

    def current_claim(self) -> dict | None:
        with self._locked():
            return self._read_raw().get("claim")
