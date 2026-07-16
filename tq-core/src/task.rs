use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Queued,
    Running,
    Held,
    Completed,
}

impl Status {
    pub fn as_str(&self) -> &'static str {
        match self {
            Status::Queued => "queued",
            Status::Running => "running",
            Status::Held => "held",
            Status::Completed => "completed",
        }
    }
}

impl std::str::FromStr for Status {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "queued" => Ok(Status::Queued),
            "running" => Ok(Status::Running),
            "held" => Ok(Status::Held),
            "completed" => Ok(Status::Completed),
            other => Err(format!("invalid status: {other}")),
        }
    }
}


#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Task {
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub notes: String,
    pub status: Status,
    pub created_at: f64,
    pub updated_at: f64,
}

impl Task {
    pub fn new(title: impl Into<String>, notes: impl Into<String>) -> Self {
        let now = now_secs();
        Task {
            id: uuid::Uuid::new_v4().simple().to_string()[..8].to_string(),
            title: title.into(),
            notes: notes.into(),
            status: Status::Queued,
            created_at: now,
            updated_at: now,
        }
    }

    pub fn touch(&mut self) {
        self.updated_at = now_secs();
    }
}

pub fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}
