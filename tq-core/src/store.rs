use std::fs;
use std::path::{Path, PathBuf};

use crate::error::{Error, Result};
use crate::lock::FileLock;
use crate::project::{Project, UNASSIGNED};
use crate::task::{Status, Task};
use crate::paths;

fn read_json<T: serde::de::DeserializeOwned + Default>(path: &Path) -> Result<T> {
    if !path.exists() {
        return Ok(T::default());
    }
    let text = fs::read_to_string(path).map_err(|source| Error::Io {
        path: path.to_path_buf(),
        source,
    })?;
    if text.trim().is_empty() {
        return Ok(T::default());
    }
    serde_json::from_str(&text).map_err(|source| Error::Json {
        path: path.to_path_buf(),
        source,
    })
}

fn write_json<T: serde::Serialize>(path: &Path, value: &T) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|source| Error::Io {
            path: parent.to_path_buf(),
            source,
        })?;
    }
    let tmp_path = path.with_extension("tmp");
    let text = serde_json::to_string_pretty(value).expect("serialize");
    fs::write(&tmp_path, text).map_err(|source| Error::Io {
        path: tmp_path.clone(),
        source,
    })?;
    fs::rename(&tmp_path, path).map_err(|source| Error::Io {
        path: path.to_path_buf(),
        source,
    })?;
    Ok(())
}

/// Project registry: which projects exist and where their directory is.
/// Does not include the always-available `_unassigned` pseudo-project.
pub struct ProjectStore {
    path: PathBuf,
}

impl ProjectStore {
    pub fn new() -> Self {
        ProjectStore {
            path: paths::registry_path(),
        }
    }

    pub fn list(&self) -> Result<Vec<Project>> {
        let _lock = FileLock::acquire(&self.path)?;
        read_json(&self.path)
    }

    pub fn get(&self, name: &str) -> Result<Option<Project>> {
        Ok(self.list()?.into_iter().find(|p| p.name == name))
    }

    pub fn add(&self, name: &str, directory: &str) -> Result<Project> {
        if name == UNASSIGNED {
            return Err(Error::ReservedProjectName(name.to_string()));
        }
        let _lock = FileLock::acquire(&self.path)?;
        let mut projects: Vec<Project> = read_json(&self.path)?;
        if projects.iter().any(|p| p.name == name) {
            return Err(Error::ProjectAlreadyExists(name.to_string()));
        }
        let project = Project::new(name, directory);
        projects.push(project.clone());
        write_json(&self.path, &projects)?;
        Ok(project)
    }

    /// Every task-bearing project name: the registry plus the implicit
    /// `_unassigned` lane.
    pub fn all_lane_names(&self) -> Result<Vec<String>> {
        let mut names: Vec<String> = self.list()?.into_iter().map(|p| p.name).collect();
        names.push(UNASSIGNED.to_string());
        Ok(names)
    }
}

impl Default for ProjectStore {
    fn default() -> Self {
        Self::new()
    }
}

/// Per-project task lane. Each registered project (plus `_unassigned`) has
/// its own JSON file and its own flock, so operations on different
/// projects never contend.
#[derive(Debug)]
pub struct TaskStore {
    project: String,
    path: PathBuf,
}

impl TaskStore {
    fn for_project_unchecked(project: &str) -> Self {
        TaskStore {
            project: project.to_string(),
            path: paths::tasks_path(project),
        }
    }

    pub fn project(&self) -> &str {
        &self.project
    }

    pub fn list(&self) -> Result<Vec<Task>> {
        let _lock = FileLock::acquire(&self.path)?;
        read_json(&self.path)
    }

    pub fn push(&self, title: &str, notes: &str) -> Result<Task> {
        let _lock = FileLock::acquire(&self.path)?;
        let mut tasks: Vec<Task> = read_json(&self.path)?;
        let task = Task::new(title, notes);
        tasks.push(task.clone());
        write_json(&self.path, &tasks)?;
        Ok(task)
    }

    pub fn get(&self, id: &str) -> Result<Task> {
        self.list()?
            .into_iter()
            .find(|t| t.id == id)
            .ok_or_else(|| Error::TaskNotFound(id.to_string()))
    }

    /// Move a task from `from` to `to`, failing if its current status isn't
    /// exactly `from`. Each named operation below (`start`, `complete`,
    /// `hold`, `release`, `requeue`) pins both ends, so no single generic
    /// entry point can be used to reach a status via an unintended edge
    /// (e.g. reaching Queued-from-Held through some other verb).
    fn move_task(&self, id: &str, from: Status, to: Status) -> Result<Task> {
        let _lock = FileLock::acquire(&self.path)?;
        let mut tasks: Vec<Task> = read_json(&self.path)?;
        let task = tasks
            .iter_mut()
            .find(|t| t.id == id)
            .ok_or_else(|| Error::TaskNotFound(id.to_string()))?;
        if task.status != from {
            return Err(Error::InvalidTransition {
                from: task.status.as_str().to_string(),
                to: to.as_str().to_string(),
            });
        }
        task.status = to;
        task.touch();
        let updated = task.clone();
        write_json(&self.path, &tasks)?;
        Ok(updated)
    }

    /// queued -> running
    pub fn start(&self, id: &str) -> Result<Task> {
        self.move_task(id, Status::Queued, Status::Running)
    }

    /// running -> completed
    pub fn complete(&self, id: &str) -> Result<Task> {
        self.move_task(id, Status::Running, Status::Completed)
    }

    /// queued -> held
    pub fn hold(&self, id: &str) -> Result<Task> {
        self.move_task(id, Status::Queued, Status::Held)
    }

    /// held -> queued. The only edge a restricted CLI mode must block.
    pub fn release(&self, id: &str) -> Result<Task> {
        self.move_task(id, Status::Held, Status::Queued)
    }

    /// running -> queued
    pub fn requeue(&self, id: &str) -> Result<Task> {
        self.move_task(id, Status::Running, Status::Queued)
    }

    pub fn remove(&self, id: &str) -> Result<()> {
        let _lock = FileLock::acquire(&self.path)?;
        let mut tasks: Vec<Task> = read_json(&self.path)?;
        let before = tasks.len();
        tasks.retain(|t| t.id != id);
        if tasks.len() == before {
            return Err(Error::TaskNotFound(id.to_string()));
        }
        write_json(&self.path, &tasks)?;
        Ok(())
    }

    pub fn edit(&self, id: &str, title: Option<&str>, notes: Option<&str>) -> Result<Task> {
        let _lock = FileLock::acquire(&self.path)?;
        let mut tasks: Vec<Task> = read_json(&self.path)?;
        let task = tasks
            .iter_mut()
            .find(|t| t.id == id)
            .ok_or_else(|| Error::TaskNotFound(id.to_string()))?;
        if let Some(title) = title {
            task.title = title.to_string();
        }
        if let Some(notes) = notes {
            task.notes = notes.to_string();
        }
        task.touch();
        let updated = task.clone();
        write_json(&self.path, &tasks)?;
        Ok(updated)
    }
}

/// Resolve a task store for `project`, verifying the project is either
/// the implicit `_unassigned` lane or present in the registry.
pub fn task_store_for(project: &str) -> Result<TaskStore> {
    if project == UNASSIGNED {
        return Ok(TaskStore::for_project_unchecked(UNASSIGNED));
    }
    if ProjectStore::new().get(project)?.is_none() {
        return Err(Error::ProjectNotFound(project.to_string()));
    }
    Ok(TaskStore::for_project_unchecked(project))
}
