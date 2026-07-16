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
import time
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


SPAWN_LAUNCH_TIMEOUT_SECONDS = 20
SPAWN_POLL_INTERVAL_SECONDS = 1.5


def _first_surface_ref(tree: dict) -> str | None:
    for window in tree.get("windows", []):
        for ws in window.get("workspaces", []):
            for pane in ws.get("panes", []):
                for s in pane.get("surfaces", []):
                    return s.get("ref")
    return None


def spawn_background_agent(
    directory: str,
    prompt_path: str,
    *,
    title: str | None = None,
    launch_cmd: str = "claude --dangerously-skip-permissions",
    ready_marker: str = "Claude Code",
) -> tuple[str, str]:
    """Create a new c11 workspace and launch an agent into it, verifying the
    launch actually took before returning.

    Two failure modes observed when spawning several agents back-to-back
    (reproduced manually, see task bc8988a3):

    1. **Lazy-init race**: a freshly created workspace's surface has no live
       PTY until c11 finishes a layout pass, so `send`ing the launch command
       immediately after `new-workspace` can drop it -- `send`'s "OK" only
       confirms the socket call was accepted, not that the PTY consumed it.
    2. **Stale `read-screen` on a background surface**: once a workspace is
       no longer the selected one, `read-screen` can keep returning a frozen
       snapshot from before the agent launched, even seconds later and even
       across repeated polls -- a caller that trusts one `read-screen` call
       (or several spaced-out ones) can wrongly conclude the launch hung.
       Re-selecting the workspace forces a fresh render.

    This selects the new workspace (forcing the layout pass) before sending
    the launch command, then polls for the agent's startup banner,
    re-selecting the workspace on each poll to force a fresh render rather
    than trusting a single `read-screen` snapshot.
    """
    if shutil.which("c11") is None:
        raise C11Unavailable("c11 CLI not found on PATH")

    args = ["new-workspace", "--cwd", directory]
    if title:
        args += ["--title", title]
    ws_out = _run_c11_raw(*args)
    workspace_ref = ws_out.strip().split()[-1]

    # Force the layout pass so the surface's PTY is actually live before we
    # send anything -- see c11's "surface initialization quirk".
    _run_c11_raw("select-workspace", "--workspace", workspace_ref)
    time.sleep(1.5)

    tree = _run_c11("tree", "--workspace", workspace_ref, "--no-layout")
    surface_ref = _first_surface_ref(tree)
    if surface_ref is None:
        raise C11Unavailable(f"workspace {workspace_ref} has no surface to launch into")

    command = f'cd {directory} && {launch_cmd} "Read {prompt_path} and follow the instructions."'
    _run_c11_raw("send", "--workspace", workspace_ref, "--surface", surface_ref, command)

    deadline = time.monotonic() + SPAWN_LAUNCH_TIMEOUT_SECONDS
    resubmitted = False
    while time.monotonic() < deadline:
        time.sleep(SPAWN_POLL_INTERVAL_SECONDS)
        # Re-select to force a fresh render -- a plain read-screen on a
        # background surface can otherwise return a stale snapshot.
        _run_c11_raw("select-workspace", "--workspace", workspace_ref)
        screen = _run_c11_raw(
            "read-screen", "--workspace", workspace_ref, "--surface", surface_ref, "--lines", "40"
        )
        if ready_marker in screen:
            return workspace_ref, surface_ref
        if not resubmitted and launch_cmd in screen:
            # The command text landed but never submitted -- Return was
            # dropped by the same lazy-init race. Resubmit once via a bare
            # keypress rather than retyping, to avoid a duplicate command
            # concatenating onto a partially-landed line.
            _run_c11_raw("send-key", "--workspace", workspace_ref, "--surface", surface_ref, "enter")
            resubmitted = True

    raise C11Unavailable(
        f"agent launch into {workspace_ref}/{surface_ref} did not land within "
        f"{SPAWN_LAUNCH_TIMEOUT_SECONDS}s"
    )


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
