from pathlib import Path

import pytest

from tq.projects import Project, ProjectStore


@pytest.fixture
def project_store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(path=tmp_path / "projects.json")


def test_project_store_add_and_list(project_store: ProjectStore) -> None:
    project_store.add("demo", "/tmp/demo", repo="me/demo")
    projects = project_store.list()
    assert len(projects) == 1
    assert projects[0] == Project(
        name="demo",
        directory="/tmp/demo",
        repo="me/demo",
        created_at=projects[0].created_at,
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


def test_new_project_has_no_pane_binding(project_store: ProjectStore) -> None:
    project = project_store.add("demo", "/tmp/demo")
    assert project.workspace_ref is None
    assert project.surface_ref is None


def test_bind_sets_pane_refs(project_store: ProjectStore) -> None:
    project_store.add("demo", "/tmp/demo")
    bound = project_store.bind("demo", "workspace:9", "surface:38")
    assert bound.workspace_ref == "workspace:9"
    assert bound.surface_ref == "surface:38"
    assert project_store.get("demo").workspace_ref == "workspace:9"


def test_bind_unknown_project_returns_none(project_store: ProjectStore) -> None:
    assert project_store.bind("ghost", "workspace:9", "surface:38") is None


def test_clear_binding_resets_pane_refs(project_store: ProjectStore) -> None:
    project_store.add("demo", "/tmp/demo")
    project_store.bind("demo", "workspace:9", "surface:38")
    cleared = project_store.clear_binding("demo")
    assert cleared.workspace_ref is None
    assert cleared.surface_ref is None
