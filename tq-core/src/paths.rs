use std::path::PathBuf;

/// Root directory for all tq state. Overridable with `TQ_HOME` (tests and
/// manual debugging); defaults to `~/.tq`.
pub fn home_dir() -> PathBuf {
    if let Ok(p) = std::env::var("TQ_HOME") {
        return PathBuf::from(p);
    }
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".tq")
}

pub fn registry_path() -> PathBuf {
    home_dir().join("projects.json")
}

pub fn tasks_path(project: &str) -> PathBuf {
    home_dir().join("projects").join(project).join("tasks.json")
}
