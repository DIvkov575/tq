from pathlib import Path

import pytest

from tq.orchestrator import OrchestratorStore


@pytest.fixture
def store(tmp_path: Path) -> OrchestratorStore:
    return OrchestratorStore(path=tmp_path / "orchestrator.json")


def test_log_and_recent(store: OrchestratorStore) -> None:
    store.log("first")
    store.log("second")
    events = store.recent()
    assert [e.message for e in events] == ["second", "first"]


def test_recent_respects_limit(store: OrchestratorStore) -> None:
    for i in range(5):
        store.log(f"event {i}")
    events = store.recent(limit=2)
    assert [e.message for e in events] == ["event 4", "event 3"]


def test_recent_empty_when_no_events(store: OrchestratorStore) -> None:
    assert store.recent() == []


def test_log_trims_to_max_events(store: OrchestratorStore) -> None:
    from tq.orchestrator import MAX_EVENTS

    for i in range(MAX_EVENTS + 5):
        store.log(f"event {i}")
    events = store.recent(limit=MAX_EVENTS + 5)
    assert len(events) == MAX_EVENTS
    assert events[0].message == f"event {MAX_EVENTS + 4}"
    assert events[-1].message == "event 5"


def test_claim_succeeds_when_unclaimed(store: OrchestratorStore) -> None:
    assert store.claim("owner-a") is True
    current = store.current_claim()
    assert current["owner"] == "owner-a"


def test_claim_fails_for_different_owner(store: OrchestratorStore) -> None:
    store.claim("owner-a")
    assert store.claim("owner-b") is False


def test_claim_by_same_owner_refreshes(store: OrchestratorStore) -> None:
    store.claim("owner-a")
    assert store.claim("owner-a") is True


def test_release_clears_claim_held_by_owner(store: OrchestratorStore) -> None:
    store.claim("owner-a")
    store.release("owner-a")
    assert store.current_claim() is None


def test_release_is_noop_for_non_holder(store: OrchestratorStore) -> None:
    store.claim("owner-a")
    store.release("owner-b")
    current = store.current_claim()
    assert current["owner"] == "owner-a"


def test_claim_succeeds_after_stale_ttl(store: OrchestratorStore, monkeypatch) -> None:
    import tq.orchestrator as orchestrator_mod

    store.claim("owner-a")

    real_time = orchestrator_mod.time.time

    def _future_time():
        return real_time() + orchestrator_mod.CLAIM_TTL_SECONDS + 1

    monkeypatch.setattr(orchestrator_mod.time, "time", _future_time)
    assert store.claim("owner-b") is True


def test_claim_ttl_is_short() -> None:
    import tq.orchestrator as orchestrator_mod

    assert orchestrator_mod.CLAIM_TTL_SECONDS <= 120
