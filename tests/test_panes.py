import json
from unittest.mock import patch

import pytest

from expqueue.panes import C11Unavailable, list_project_workspaces, spawn_background_agent


def _completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    class _Result:
        pass

    r = _Result()
    r.stdout = stdout
    r.returncode = returncode
    r.stderr = stderr
    return r


LIST_WORKSPACES = {
    "workspaces": [
        {"ref": "workspace:1", "title": "demo", "current_directory": "/tmp/demo"},
        {"ref": "workspace:2", "title": "demo-sub", "current_directory": "/tmp/demo/sub"},
        {"ref": "workspace:3", "title": "other", "current_directory": "/tmp/other"},
    ]
}

TREE_WS1 = {
    "windows": [
        {
            "workspaces": [
                {
                    "panes": [
                        {
                            "surfaces": [
                                {"ref": "surface:10", "title": "agent"},
                            ]
                        }
                    ]
                }
            ]
        }
    ]
}

TREE_WS2 = {
    "windows": [
        {
            "workspaces": [
                {
                    "panes": [
                        {
                            "surfaces": [
                                {"ref": "surface:20", "title": "agent2"},
                            ]
                        }
                    ]
                }
            ]
        }
    ]
}

GET_METADATA_WORKING = {"metadata": {"activity": "working"}}


def _fake_run(args, **kwargs):
    # args like ["c11", "--json", "list-workspaces"] or [..., "tree", "--workspace", "workspace:1", ...]
    cmd = args[2:]
    if cmd[0] == "list-workspaces":
        return _completed(stdout=json.dumps(LIST_WORKSPACES))
    if cmd[0] == "tree":
        ws = cmd[cmd.index("--workspace") + 1]
        payload = TREE_WS1 if ws == "workspace:1" else TREE_WS2
        return _completed(stdout=json.dumps(payload))
    if cmd[0] == "get-metadata":
        return _completed(stdout=json.dumps(GET_METADATA_WORKING))
    raise AssertionError(f"unexpected c11 call: {cmd}")


@patch("expqueue.panes.shutil.which", return_value="/usr/bin/c11")
@patch("expqueue.panes.subprocess.run", side_effect=_fake_run)
def test_matches_directory_and_subdirectory(mock_run, mock_which) -> None:
    workspaces = list_project_workspaces("/tmp/demo")
    refs = {w.workspace_ref for w in workspaces}
    assert refs == {"workspace:1", "workspace:2"}


@patch("expqueue.panes.shutil.which", return_value="/usr/bin/c11")
@patch("expqueue.panes.subprocess.run", side_effect=_fake_run)
def test_excludes_unrelated_directory(mock_run, mock_which) -> None:
    workspaces = list_project_workspaces("/tmp/demo")
    titles = {w.title for w in workspaces}
    assert "other" not in titles


@patch("expqueue.panes.shutil.which", return_value="/usr/bin/c11")
@patch("expqueue.panes.subprocess.run", side_effect=_fake_run)
def test_includes_surface_activity(mock_run, mock_which) -> None:
    workspaces = list_project_workspaces("/tmp/demo")
    ws1 = next(w for w in workspaces if w.workspace_ref == "workspace:1")
    assert ws1.surfaces[0].activity == "working"


@patch("expqueue.panes.shutil.which", return_value=None)
def test_raises_when_c11_missing(mock_which) -> None:
    with pytest.raises(C11Unavailable):
        list_project_workspaces("/tmp/demo")


@patch("expqueue.panes.shutil.which", return_value="/usr/bin/c11")
@patch(
    "expqueue.panes.subprocess.run",
    return_value=_completed(returncode=1, stderr="Socket not found"),
)
def test_raises_on_nonzero_exit(mock_run, mock_which) -> None:
    with pytest.raises(C11Unavailable):
        list_project_workspaces("/tmp/demo")


TREE_SPAWN = {
    "windows": [
        {
            "workspaces": [
                {"panes": [{"surfaces": [{"ref": "surface:23", "title": "shell"}]}]},
            ]
        }
    ]
}


@patch("expqueue.panes.shutil.which", return_value="/usr/bin/c11")
@patch("expqueue.panes.time.sleep")
@patch("expqueue.panes.time.monotonic", side_effect=[0, 1])
@patch("expqueue.panes.subprocess.run")
def test_spawn_background_agent_happy_path(mock_run, mock_monotonic, mock_sleep, mock_which) -> None:
    mock_run.side_effect = [
        _completed(stdout="OK workspace:5"),  # new-workspace
        _completed(stdout="OK"),  # select-workspace (initial)
        _completed(stdout=json.dumps(TREE_SPAWN)),  # --json tree
        _completed(stdout="OK"),  # send
        _completed(stdout="OK"),  # select-workspace (poll)
        _completed(stdout="Claude Code v2.1.205 ready"),  # read-screen
    ]
    workspace_ref, surface_ref = spawn_background_agent("/tmp/demo", "/tmp/prompt.md")
    assert workspace_ref == "workspace:5"
    assert surface_ref == "surface:23"


@patch("expqueue.panes.shutil.which", return_value="/usr/bin/c11")
@patch("expqueue.panes.time.sleep")
@patch("expqueue.panes.time.monotonic", side_effect=[0, 1, 2])
@patch("expqueue.panes.subprocess.run")
def test_spawn_background_agent_resubmits_dropped_return(
    mock_run, mock_monotonic, mock_sleep, mock_which
) -> None:
    """Simulates the lazy-init race: the launch command's text lands but the
    Return is dropped, so the first poll only shows the still-unsubmitted
    command; a bare `enter` keypress is resubmitted and the second poll
    shows the agent actually launched."""
    mock_run.side_effect = [
        _completed(stdout="OK workspace:5"),  # new-workspace
        _completed(stdout="OK"),  # select-workspace (initial)
        _completed(stdout=json.dumps(TREE_SPAWN)),  # --json tree
        _completed(stdout="OK"),  # send
        _completed(stdout="OK"),  # select-workspace (poll 1)
        _completed(stdout='❯ claude --dangerously-skip-permissions "..."'),  # read-screen: stuck
        _completed(stdout="OK"),  # send-key enter (resubmit)
        _completed(stdout="OK"),  # select-workspace (poll 2)
        _completed(stdout="Claude Code v2.1.205 ready"),  # read-screen: launched
    ]
    workspace_ref, surface_ref = spawn_background_agent("/tmp/demo", "/tmp/prompt.md")
    assert workspace_ref == "workspace:5"
    assert surface_ref == "surface:23"
    resubmit_calls = [c for c in mock_run.call_args_list if c.args[0][1] == "send-key"]
    assert len(resubmit_calls) == 1


@patch("expqueue.panes.shutil.which", return_value="/usr/bin/c11")
@patch("expqueue.panes.time.sleep")
@patch("expqueue.panes.time.monotonic", side_effect=[0, 25])
@patch("expqueue.panes.subprocess.run")
def test_spawn_background_agent_raises_when_launch_never_lands(
    mock_run, mock_monotonic, mock_sleep, mock_which
) -> None:
    mock_run.side_effect = [
        _completed(stdout="OK workspace:5"),  # new-workspace
        _completed(stdout="OK"),  # select-workspace (initial)
        _completed(stdout=json.dumps(TREE_SPAWN)),  # --json tree
        _completed(stdout="OK"),  # send
    ]
    with pytest.raises(C11Unavailable):
        spawn_background_agent("/tmp/demo", "/tmp/prompt.md")
