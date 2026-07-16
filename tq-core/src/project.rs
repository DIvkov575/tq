use serde::{Deserialize, Serialize};

use crate::task::now_secs;

/// Pseudo-project name for untriaged tasks. Always implicitly available,
/// never appears in the registry, cannot be registered or removed.
pub const UNASSIGNED: &str = "_unassigned";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Project {
    pub name: String,
    pub directory: String,
    pub created_at: f64,
}

impl Project {
    pub fn new(name: impl Into<String>, directory: impl Into<String>) -> Self {
        Project {
            name: name.into(),
            directory: directory.into(),
            created_at: now_secs(),
        }
    }
}
