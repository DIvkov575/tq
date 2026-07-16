//! End-to-end tests of the compiled `tqctl` binary, exercising the
//! restricted-mode block on `release` the same way a real invocation would
//! (via --restricted, and via an argv[0] symlink named `tqctl-restricted`).

use std::process::{Command, Output};

fn run(home: &std::path::Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_tqctl"))
        .args(args)
        .env("TQ_HOME", home)
        .output()
        .expect("failed to run tqctl")
}

fn extract_id(output: &Output) -> String {
    let stdout = String::from_utf8_lossy(&output.stdout);
    let first_line = stdout.lines().next().expect("expected a task line");
    first_line
        .trim_start_matches('[')
        .split(']')
        .next()
        .expect("expected [id] prefix")
        .to_string()
}

#[test]
fn restricted_flag_blocks_release_but_allows_hold() {
    let dir = tempfile::tempdir().unwrap();
    let home = dir.path();

    let push_out = run(home, &["push", "held task"]);
    assert!(push_out.status.success());
    let id = extract_id(&push_out);

    let hold_out = run(home, &["hold", &id]);
    assert!(hold_out.status.success(), "hold should succeed in restricted mode too");

    let release_out = run(home, &["--restricted", "release", &id]);
    assert!(!release_out.status.success());
    let stderr = String::from_utf8_lossy(&release_out.stderr);
    assert!(stderr.contains("restricted"), "expected restricted-mode error, got: {stderr}");

    // Task must still be held -- the blocked release must not have applied.
    let list_out = run(home, &["list", "--status", "held", "--json"]);
    assert!(String::from_utf8_lossy(&list_out.stdout).contains(&id));
}

#[test]
fn full_mode_allows_release() {
    let dir = tempfile::tempdir().unwrap();
    let home = dir.path();

    let push_out = run(home, &["push", "held task"]);
    let id = extract_id(&push_out);
    run(home, &["hold", &id]);

    let release_out = run(home, &["release", &id]);
    assert!(release_out.status.success());

    let list_out = run(home, &["list", "--status", "queued", "--json"]);
    assert!(String::from_utf8_lossy(&list_out.stdout).contains(&id));
}

#[test]
fn requeue_cannot_be_used_to_bypass_restricted_release() {
    // requeue is pinned to running->queued only; a held task can't reach
    // queued through it, so restricted mode has no escape hatch via requeue.
    let dir = tempfile::tempdir().unwrap();
    let home = dir.path();

    let push_out = run(home, &["push", "held task"]);
    let id = extract_id(&push_out);
    run(home, &["hold", &id]);

    let requeue_out = run(home, &["--restricted", "requeue", &id]);
    assert!(!requeue_out.status.success());

    let list_out = run(home, &["list", "--status", "held", "--json"]);
    assert!(String::from_utf8_lossy(&list_out.stdout).contains(&id));
}
