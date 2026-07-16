from pathlib import Path

import pytest

from tq.store import QueueStore


@pytest.fixture
def store(tmp_path: Path) -> QueueStore:
    return QueueStore(path=tmp_path / "queue.json")


def test_push_and_pop(store: QueueStore) -> None:
    store.push("first")
    store.push("second")
    popped = store.pop()
    assert popped.title == "first"
    assert popped.status == "in_progress"


def test_push_with_project(store: QueueStore) -> None:
    task = store.push("with project", project="demo")
    assert task.project == "demo"


def test_edit_project(store: QueueStore) -> None:
    task = store.push("no project yet")
    updated = store.edit(task.id, project="demo")
    assert updated.project == "demo"


def test_pop_scoped_to_project(store: QueueStore) -> None:
    store.push("general task")
    demo_task = store.push("demo task", project="demo")
    popped = store.pop(project="demo")
    assert popped.id == demo_task.id
    assert popped.status == "in_progress"
    # the general task is untouched and still queued
    assert store.list(status="queued")[0].title == "general task"


def test_pop_scoped_to_project_returns_none_when_empty(store: QueueStore) -> None:
    store.push("general task")
    assert store.pop(project="demo") is None


def test_list_filters_by_status(store: QueueStore) -> None:
    store.push("a")
    t2 = store.push("b")
    store.update_status(t2.id, "done")
    queued = store.list(status="queued")
    done = store.list(status="done")
    assert len(queued) == 1
    assert len(done) == 1
