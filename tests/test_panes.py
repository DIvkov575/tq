import json
from unittest.mock import patch

import pytest

from tq.panes import (
    C11Unavailable,
    bind_project_pane,
    ensure_shared_workspace,
    launch_agent_in_surface,
    surface_exists,
)


def _completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    class _Result:
        pass

    r = _Result()
    r.stdout = stdout
    r.returncode = returncode
    r.stderr = stderr
    return r


TREE_FOUND = {
    "windows": [
        {
            "workspaces": [
                {
                    "panes": [
                        {"ref": "pane:21", "surfaces": [{"ref": "surface:37", "title": "shell"}]}
                    ]
                }
            ]
        }
    ]
}


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_surface_exists_true_when_tree_succeeds(mock_run, mock_which) -> None:
    mock_run.return_value = _completed(stdout=json.dumps(TREE_FOUND))
    assert surface_exists("workspace:9", "surface:37") is True


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_surface_exists_false_when_surface_missing_from_tree(mock_run, mock_which) -> None:
    mock_run.return_value = _completed(stdout=json.dumps({"windows": []}))
    assert surface_exists("workspace:9", "surface:999") is False


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_surface_exists_false_when_workspace_command_fails(mock_run, mock_which) -> None:
    mock_run.return_value = _completed(returncode=1, stderr="Socket not found")
    assert surface_exists("workspace:9", "surface:37") is False


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_ensure_shared_workspace_creates_when_none_given(mock_run, mock_which) -> None:
    mock_run.return_value = _completed(stdout="OK workspace:9")
    ref = ensure_shared_workspace(existing_ref=None)
    assert ref == "workspace:9"
    args = mock_run.call_args.args[0]
    assert args[1] == "new-workspace"


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_ensure_shared_workspace_reuses_live_ref(mock_run, mock_which) -> None:
    mock_run.return_value = _completed(stdout=json.dumps(TREE_FOUND))
    ref = ensure_shared_workspace(existing_ref="workspace:9")
    assert ref == "workspace:9"
    args = mock_run.call_args.args[0]
    assert args[2] == "tree"  # args[1] is "--json", prepended by _run_c11


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_ensure_shared_workspace_respawns_when_ref_is_dead(mock_run, mock_which) -> None:
    mock_run.side_effect = [
        _completed(returncode=1, stderr="workspace not found"),  # tree check fails
        _completed(stdout="OK workspace:12"),  # new-workspace
    ]
    ref = ensure_shared_workspace(existing_ref="workspace:9")
    assert ref == "workspace:12"


TREE_SPAWN = {
    "windows": [
        {
            "workspaces": [
                {"panes": [{"ref": "pane:21", "surfaces": [{"ref": "surface:37", "title": "shell"}]}]}
            ]
        }
    ]
}


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.time.sleep")
@patch("tq.panes.time.monotonic", side_effect=[0, 1])
@patch("tq.panes.subprocess.run")
def test_launch_agent_in_surface_happy_path(mock_run, mock_monotonic, mock_sleep, mock_which) -> None:
    mock_run.side_effect = [
        _completed(stdout="OK"),  # select-workspace
        _completed(stdout="OK"),  # send
        _completed(stdout="OK"),  # select-workspace (poll)
        _completed(stdout="Claude Code v2.1.205 ready"),  # read-screen
    ]
    launch_agent_in_surface(
        "workspace:9", "surface:37", "/tmp/demo", "/tmp/prompt.md"
    )  # should not raise


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.time.sleep")
@patch("tq.panes.time.monotonic", side_effect=[0, 25])
@patch("tq.panes.subprocess.run")
def test_launch_agent_in_surface_raises_when_launch_never_lands(
    mock_run, mock_monotonic, mock_sleep, mock_which
) -> None:
    mock_run.side_effect = [
        _completed(stdout="OK"),  # select-workspace
        _completed(stdout="OK"),  # send
    ]
    with pytest.raises(C11Unavailable):
        launch_agent_in_surface("workspace:9", "surface:37", "/tmp/demo", "/tmp/prompt.md")


@patch("tq.panes.shutil.which", return_value="/usr/bin/c11")
@patch("tq.panes.subprocess.run")
def test_bind_project_pane_creates_surface_and_launches(mock_run, mock_which) -> None:
    mock_run.side_effect = [
        _completed(stdout="OK surface:38 pane:21 workspace:9"),  # new-surface
        _completed(stdout="OK"),  # select-workspace (inside launch_agent_in_surface)
        _completed(stdout="OK"),  # send
        _completed(stdout="OK"),  # select-workspace (poll)
        _completed(stdout="Claude Code v2.1.205 ready"),  # read-screen
    ]
    with patch("tq.panes.time.sleep"), patch("tq.panes.time.monotonic", side_effect=[0, 1]):
        workspace_ref, surface_ref = bind_project_pane(
            shared_workspace_ref="workspace:9",
            pane_ref="pane:21",
            directory="/tmp/demo",
            prompt_path="/tmp/prompt.md",
        )
    assert workspace_ref == "workspace:9"
    assert surface_ref == "surface:38"


@patch("tq.panes.shutil.which", return_value=None)
def test_bind_project_pane_raises_when_c11_missing(mock_which) -> None:
    with pytest.raises(C11Unavailable):
        bind_project_pane(
            shared_workspace_ref="workspace:9",
            pane_ref="pane:21",
            directory="/tmp/demo",
            prompt_path="/tmp/prompt.md",
        )
