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
