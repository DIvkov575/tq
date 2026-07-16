"""Discover c11 workspaces/surfaces belonging to a project.

Shells out to the `c11` CLI to enumerate workspaces and match each one's
current working directory against a project's registered directory. A
workspace "belongs" to a project when its cwd is the project directory or a
subdirectory of it — this mirrors c11's own workspace-per-project
convention, so no extra tagging step is required for existing panes.

This module only discovers candidate panes; deciding which one is actually
idle and should receive a task is the orchestrator's job (it reads each
surface's screen to judge that) — see the orchestrator-loop skill.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


class C11Unavailable(RuntimeError):
    """The c11 CLI is missing, its socket is unreachable, or a call failed."""


@dataclass
class Surface:
    ref: str
    title: str
    activity: str | None  # "working" / "idle" / None if unknown

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProjectWorkspace:
    workspace_ref: str
    title: str
    directory: str
    surfaces: list[Surface]

    def to_dict(self) -> dict:
        return {
            "workspace_ref": self.workspace_ref,
            "title": self.title,
            "directory": self.directory,
            "surfaces": [s.to_dict() for s in self.surfaces],
        }


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


def _is_under(cwd: str, directory: str) -> bool:
    try:
        Path(cwd).resolve().relative_to(Path(directory).resolve())
    except ValueError:
        return False
    return True


def _surface_activity(workspace_ref: str, surface_ref: str) -> str | None:
    try:
        meta = _run_c11("get-metadata", "--workspace", workspace_ref, "--surface", surface_ref)
    except C11Unavailable:
        return None
    return meta.get("metadata", {}).get("activity")


def _list_surfaces(workspace_ref: str) -> list[Surface]:
    tree = _run_c11("tree", "--workspace", workspace_ref, "--no-layout")
    surfaces: list[Surface] = []
    for window in tree.get("windows", []):
        for ws in window.get("workspaces", []):
            for pane in ws.get("panes", []):
                for s in pane.get("surfaces", []):
                    ref = s.get("ref")
                    surfaces.append(
                        Surface(
                            ref=ref,
                            title=s.get("title", ""),
                            activity=_surface_activity(workspace_ref, ref),
                        )
                    )
    return surfaces


def list_project_workspaces(directory: str) -> list[ProjectWorkspace]:
    """Find c11 workspaces whose cwd is `directory` or a subdirectory of it."""
    data = _run_c11("list-workspaces")
    matches: list[ProjectWorkspace] = []
    for ws in data.get("workspaces", []):
        cwd = ws.get("current_directory")
        if not cwd or not _is_under(cwd, directory):
            continue
        ref = ws["ref"]
        matches.append(
            ProjectWorkspace(
                workspace_ref=ref,
                title=ws.get("title", ""),
                directory=cwd,
                surfaces=_list_surfaces(ref),
            )
        )
    return matches
