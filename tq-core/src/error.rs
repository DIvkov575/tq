use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("io error at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },

    #[error("malformed json at {path}: {source}")]
    Json {
        path: PathBuf,
        #[source]
        source: serde_json::Error,
    },

    #[error("project not found: {0}")]
    ProjectNotFound(String),

    #[error("project already exists: {0}")]
    ProjectAlreadyExists(String),

    #[error("task not found: {0}")]
    TaskNotFound(String),

    #[error("invalid status transition: {from} -> {to}")]
    InvalidTransition { from: String, to: String },

    #[error("operation not permitted in restricted mode: {0}")]
    Restricted(String),

    #[error("the {0} project name is reserved")]
    ReservedProjectName(String),
}

pub type Result<T> = std::result::Result<T, Error>;
