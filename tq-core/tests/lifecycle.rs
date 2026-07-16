//! Integration tests against a real (temp-dir) filesystem store.
//!
//! Tests share the process-global `TQ_HOME` env var, so they're serialized
//! behind `ENV_LOCK` to avoid one test's `TQ_HOME` leaking into another
//! running concurrently on a different thread.

use std::sync::Mutex;

use tq_core::{task_store_for, Error, ProjectStore, Status, UNASSIGNED};

static ENV_LOCK: Mutex<()> = Mutex::new(());

/// Points TQ_HOME at a fresh temp dir for the duration of the guard.
struct TempHome {
    _guard: std::sync::MutexGuard<'static, ()>,
    dir: tempfile::TempDir,
}

impl TempHome {
    fn new() -> Self {
        let guard = ENV_LOCK.lock().unwrap();
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("TQ_HOME", dir.path());
        TempHome { _guard: guard, dir }
    }
}

impl Drop for TempHome {
    fn drop(&mut self) {
        std::env::remove_var("TQ_HOME");
        let _ = &self.dir;
    }
}

#[test]
fn unassigned_lane_works_without_registration() {
    let _home = TempHome::new();
    let store = task_store_for(UNASSIGNED).unwrap();
    let task = store.push("do a thing", "").unwrap();
    assert_eq!(task.status, Status::Queued);

    let listed = store.list().unwrap();
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].id, task.id);
}

#[test]
fn pushing_to_unregistered_project_fails() {
    let _home = TempHome::new();
    let err = task_store_for("nope").unwrap_err();
    assert!(matches!(err, Error::ProjectNotFound(name) if name == "nope"));
}

#[test]
fn project_registration_round_trips() {
    let _home = TempHome::new();
    let registry = ProjectStore::new();
    registry.add("demo", "/tmp/demo").unwrap();

    let projects = registry.list().unwrap();
    assert_eq!(projects.len(), 1);
    assert_eq!(projects[0].name, "demo");
    assert_eq!(projects[0].directory, "/tmp/demo");

    let lanes = registry.all_lane_names().unwrap();
    assert!(lanes.contains(&"demo".to_string()));
    assert!(lanes.contains(&UNASSIGNED.to_string()));
}

#[test]
fn duplicate_project_name_rejected() {
    let _home = TempHome::new();
    let registry = ProjectStore::new();
    registry.add("demo", "/tmp/demo").unwrap();
    let err = registry.add("demo", "/tmp/other").unwrap_err();
    assert!(matches!(err, Error::ProjectAlreadyExists(name) if name == "demo"));
}

#[test]
fn reserved_project_name_rejected() {
    let _home = TempHome::new();
    let registry = ProjectStore::new();
    let err = registry.add(UNASSIGNED, "/tmp/x").unwrap_err();
    assert!(matches!(err, Error::ReservedProjectName(_)));
}

#[test]
fn full_lifecycle_queued_to_completed() {
    let _home = TempHome::new();
    let store = task_store_for(UNASSIGNED).unwrap();
    let task = store.push("ship it", "").unwrap();

    let started = store.start(&task.id).unwrap();
    assert_eq!(started.status, Status::Running);

    let completed = store.complete(&task.id).unwrap();
    assert_eq!(completed.status, Status::Completed);
}

#[test]
fn hold_and_release_round_trip() {
    let _home = TempHome::new();
    let store = task_store_for(UNASSIGNED).unwrap();
    let task = store.push("pause me", "").unwrap();

    let held = store.hold(&task.id).unwrap();
    assert_eq!(held.status, Status::Held);

    let released = store.release(&task.id).unwrap();
    assert_eq!(released.status, Status::Queued);
}

#[test]
fn cannot_complete_a_queued_task_directly() {
    let _home = TempHome::new();
    let store = task_store_for(UNASSIGNED).unwrap();
    let task = store.push("skip ahead", "").unwrap();

    let err = store.complete(&task.id).unwrap_err();
    assert!(matches!(err, Error::InvalidTransition { .. }));
}

#[test]
fn cannot_release_a_task_that_is_not_held() {
    let _home = TempHome::new();
    let store = task_store_for(UNASSIGNED).unwrap();
    let task = store.push("still queued", "").unwrap();

    let err = store.release(&task.id).unwrap_err();
    assert!(matches!(err, Error::InvalidTransition { .. }));
}

#[test]
fn requeue_only_valid_from_running() {
    let _home = TempHome::new();
    let store = task_store_for(UNASSIGNED).unwrap();
    let task = store.push("in flight", "").unwrap();
    store.start(&task.id).unwrap();

    let requeued = store.requeue(&task.id).unwrap();
    assert_eq!(requeued.status, Status::Queued);

    // Now queued again -- requeue from queued should fail (only running->queued is valid).
    let err = store.requeue(&task.id).unwrap_err();
    assert!(matches!(err, Error::InvalidTransition { .. }));
}

#[test]
fn remove_deletes_task_entirely() {
    let _home = TempHome::new();
    let store = task_store_for(UNASSIGNED).unwrap();
    let task = store.push("temporary", "").unwrap();
    store.remove(&task.id).unwrap();

    assert!(store.list().unwrap().is_empty());
    let err = store.remove(&task.id).unwrap_err();
    assert!(matches!(err, Error::TaskNotFound(_)));
}

#[test]
fn edit_updates_title_and_notes() {
    let _home = TempHome::new();
    let store = task_store_for(UNASSIGNED).unwrap();
    let task = store.push("original", "orig notes").unwrap();

    let edited = store
        .edit(&task.id, Some("renamed"), Some("new notes"))
        .unwrap();
    assert_eq!(edited.title, "renamed");
    assert_eq!(edited.notes, "new notes");
}

#[test]
fn projects_have_independent_task_lanes() {
    let _home = TempHome::new();
    let registry = ProjectStore::new();
    registry.add("alpha", "/tmp/alpha").unwrap();
    registry.add("beta", "/tmp/beta").unwrap();

    let alpha_store = task_store_for("alpha").unwrap();
    let beta_store = task_store_for("beta").unwrap();

    alpha_store.push("alpha task", "").unwrap();
    beta_store.push("beta task 1", "").unwrap();
    beta_store.push("beta task 2", "").unwrap();

    assert_eq!(alpha_store.list().unwrap().len(), 1);
    assert_eq!(beta_store.list().unwrap().len(), 2);
}
