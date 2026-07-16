from pathlib import Path

import pytest

from tq.config import Config, ConfigStore


@pytest.fixture
def store(tmp_path: Path) -> ConfigStore:
    return ConfigStore(path=tmp_path / "config.json")


def test_default_config_has_no_orchestrator_or_workspace(store: ConfigStore) -> None:
    config = store.load()
    assert config.shared_workspace_ref is None
    assert config.orchestrator_workspace_ref is None
    assert config.orchestrator_surface_ref is None


def test_set_shared_workspace_ref(store: ConfigStore) -> None:
    store.set_shared_workspace_ref("workspace:9")
    assert store.load().shared_workspace_ref == "workspace:9"


def test_set_orchestrator_pane(store: ConfigStore) -> None:
    store.set_orchestrator_pane("workspace:9", "surface:38")
    config = store.load()
    assert config.orchestrator_workspace_ref == "workspace:9"
    assert config.orchestrator_surface_ref == "surface:38"


def test_clear_orchestrator_pane(store: ConfigStore) -> None:
    store.set_orchestrator_pane("workspace:9", "surface:38")
    store.clear_orchestrator_pane()
    config = store.load()
    assert config.orchestrator_workspace_ref is None
    assert config.orchestrator_surface_ref is None
