from pathlib import Path

import pytest

from expqueue.projects import Project, ProjectStore
from expqueue.store import QueueStore


@pytest.fixture
def store(tmp_path: Path) -> QueueStore:
    return QueueStore(path=tmp_path / "queue.json")


@pytest.fixture
def project_store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(path=tmp_path / "projects.json")


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


def test_project_store_add_and_list(project_store: ProjectStore) -> None:
    project_store.add("demo", "/tmp/demo", repo="me/demo")
    projects = project_store.list()
    assert len(projects) == 1
    assert projects[0] == Project(
        name="demo", directory="/tmp/demo", repo="me/demo", created_at=projects[0].created_at
    )


def test_project_store_duplicate_name_raises(project_store: ProjectStore) -> None:
    project_store.add("demo", "/tmp/demo")
    with pytest.raises(ValueError):
        project_store.add("demo", "/tmp/other")


def test_project_store_duplicate_name_with_init_dir_does_not_create_directory(
    tmp_path: Path,
) -> None:
    project_store = ProjectStore(path=tmp_path / "projects.json")
    project_store.add("demo", str(tmp_path / "existing"))
    orphan = tmp_path / "orphan"
    with pytest.raises(ValueError):
        project_store.add("demo", str(orphan), init_dir=True)
    assert not orphan.exists()


def test_project_store_init_dir_creates_missing_directory(tmp_path: Path) -> None:
    project_store = ProjectStore(path=tmp_path / "projects.json")
    target = tmp_path / "new-project"
    assert not target.exists()
    project = project_store.add("demo", str(target), init_dir=True)
    assert target.is_dir()
    assert (target / ".git").is_dir()
    assert project.directory == str(target)


def test_project_store_init_dir_leaves_existing_directory_alone(tmp_path: Path) -> None:
    project_store = ProjectStore(path=tmp_path / "projects.json")
    target = tmp_path / "already-here"
    target.mkdir()
    marker = target / "marker.txt"
    marker.write_text("keep me")
    project_store.add("demo", str(target), init_dir=True)
    assert marker.read_text() == "keep me"
    assert not (target / ".git").exists()


def test_project_store_add_without_init_dir_does_not_create_directory(tmp_path: Path) -> None:
    project_store = ProjectStore(path=tmp_path / "projects.json")
    target = tmp_path / "never-created"
    project = project_store.add("demo", str(target))
    assert not target.exists()
    assert project.directory == str(target)
