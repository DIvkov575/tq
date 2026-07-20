use tq_core::{task_store_for, ProjectStore, Status, Task};

pub const COLUMNS: [Status; 4] = [
    Status::Queued,
    Status::Running,
    Status::Held,
    Status::Completed,
];

pub fn column_label(s: Status) -> &'static str {
    match s {
        Status::Queued => "QUEUED",
        Status::Running => "RUNNING",
        Status::Held => "HELD",
        Status::Completed => "COMPLETED",
    }
}

#[derive(Default)]
pub struct InputState {
    pub active: bool,
    pub prompt: String,
    pub buffer: String,
    /// What to do with the input once submitted.
    pub purpose: InputPurpose,
}

#[derive(Default, Clone, Copy, PartialEq, Eq)]
pub enum InputPurpose {
    #[default]
    None,
    AddTask,
    EditTitle,
    NewProjectName,
    NewProjectDir { name_captured: bool },
}

pub struct App {
    pub lanes: Vec<String>,
    pub lane_idx: usize,
    pub tasks: Vec<Task>,
    pub column_idx: usize,
    pub row_idx: [usize; 4],
    pub status_message: String,
    pub input: InputState,
    pub pending_project_name: String,
    pub help_open: bool,
    pub should_quit: bool,
}

impl App {
    pub fn load() -> tq_core::Result<Self> {
        let lanes = ProjectStore::new().all_lane_names()?;
        let mut app = App {
            lanes,
            lane_idx: 0,
            tasks: Vec::new(),
            column_idx: 0,
            row_idx: [0; 4],
            status_message: String::new(),
            input: InputState::default(),
            pending_project_name: String::new(),
            help_open: false,
            should_quit: false,
        };
        app.refresh()?;
        Ok(app)
    }

    pub fn current_lane(&self) -> &str {
        &self.lanes[self.lane_idx]
    }

    pub fn refresh(&mut self) -> tq_core::Result<()> {
        self.lanes = ProjectStore::new().all_lane_names()?;
        if self.lane_idx >= self.lanes.len() {
            self.lane_idx = 0;
        }
        let lane = self.current_lane().to_string();
        self.tasks = task_store_for(&lane)?.list()?;
        Ok(())
    }

    pub fn tasks_in(&self, status: Status) -> Vec<&Task> {
        self.tasks.iter().filter(|t| t.status == status).collect()
    }

    pub fn current_column(&self) -> Status {
        COLUMNS[self.column_idx]
    }

    pub fn selected_task(&self) -> Option<&Task> {
        let tasks = self.tasks_in(self.current_column());
        tasks.get(self.row_idx[self.column_idx]).copied()
    }

    pub fn next_lane(&mut self) {
        self.lane_idx = (self.lane_idx + 1) % self.lanes.len();
        let _ = self.refresh();
    }

    pub fn prev_lane(&mut self) {
        self.lane_idx = (self.lane_idx + self.lanes.len() - 1) % self.lanes.len();
        let _ = self.refresh();
    }

    pub fn move_column(&mut self, delta: i32) {
        let len = COLUMNS.len() as i32;
        self.column_idx = ((self.column_idx as i32 + delta + len) % len) as usize;
    }

    pub fn move_row(&mut self, delta: i32) {
        let col = self.column_idx;
        let count = self.tasks_in(COLUMNS[col]).len();
        if count == 0 {
            self.row_idx[col] = 0;
            return;
        }
        let cur = self.row_idx[col] as i32;
        let next = (cur + delta).clamp(0, count as i32 - 1);
        self.row_idx[col] = next as usize;
    }

    fn clamp_rows(&mut self) {
        for (i, status) in COLUMNS.iter().enumerate() {
            let count = self.tasks_in(*status).len();
            if count == 0 {
                self.row_idx[i] = 0;
            } else if self.row_idx[i] >= count {
                self.row_idx[i] = count - 1;
            }
        }
    }

    fn set_status(&mut self, msg: impl Into<String>) {
        self.status_message = msg.into();
    }

    fn set_error(&mut self, err: tq_core::Error) {
        self.status_message = format!("error: {err}");
    }

    pub fn open_add_task(&mut self) {
        self.input = InputState {
            active: true,
            prompt: format!("New task title ({}):", self.current_lane()),
            buffer: String::new(),
            purpose: InputPurpose::AddTask,
        };
    }

    pub fn open_edit_title(&mut self) {
        let Some(task) = self.selected_task() else {
            return;
        };
        self.input = InputState {
            active: true,
            prompt: "Edit title:".to_string(),
            buffer: task.title.clone(),
            purpose: InputPurpose::EditTitle,
        };
    }

    pub fn open_new_project(&mut self) {
        self.pending_project_name.clear();
        self.input = InputState {
            active: true,
            prompt: "New project name:".to_string(),
            buffer: String::new(),
            purpose: InputPurpose::NewProjectName,
        };
    }

    pub fn cancel_input(&mut self) {
        self.input = InputState::default();
    }

    pub fn submit_input(&mut self) {
        let purpose = self.input.purpose;
        let value = self.input.buffer.trim().to_string();
        self.input = InputState::default();
        if value.is_empty() && !matches!(purpose, InputPurpose::NewProjectDir { .. }) {
            return;
        }

        match purpose {
            InputPurpose::None => {}
            InputPurpose::AddTask => {
                let lane = self.current_lane().to_string();
                match task_store_for(&lane).and_then(|s| s.push(&value, "")) {
                    Ok(_) => self.set_status(format!("added task to {lane}")),
                    Err(e) => self.set_error(e),
                }
            }
            InputPurpose::EditTitle => {
                if let Some(task) = self.selected_task() {
                    let id = task.id.clone();
                    let lane = self.current_lane().to_string();
                    match task_store_for(&lane).and_then(|s| s.edit(&id, Some(&value), None)) {
                        Ok(_) => self.set_status("title updated"),
                        Err(e) => self.set_error(e),
                    }
                }
            }
            InputPurpose::NewProjectName => {
                self.pending_project_name = value;
                self.input = InputState {
                    active: true,
                    prompt: format!("Directory for {}:", self.pending_project_name),
                    buffer: String::new(),
                    purpose: InputPurpose::NewProjectDir {
                        name_captured: true,
                    },
                };
                return;
            }
            InputPurpose::NewProjectDir { .. } => {
                let name = self.pending_project_name.clone();
                match ProjectStore::new().add(&name, &value) {
                    Ok(_) => self.set_status(format!("registered project {name}")),
                    Err(e) => self.set_error(e),
                }
            }
        }
        let _ = self.refresh();
        self.clamp_rows();
    }

    pub fn input_char(&mut self, c: char) {
        self.input.buffer.push(c);
    }

    pub fn input_backspace(&mut self) {
        self.input.buffer.pop();
    }

    pub fn act_start(&mut self) {
        self.with_selected(|store, id| store.start(id));
    }

    pub fn act_complete(&mut self) {
        self.with_selected(|store, id| store.complete(id));
    }

    pub fn act_hold(&mut self) {
        self.with_selected(|store, id| store.hold(id));
    }

    pub fn act_release(&mut self) {
        self.with_selected(|store, id| store.release(id));
    }

    pub fn act_requeue(&mut self) {
        self.with_selected(|store, id| store.requeue(id));
    }

    pub fn act_delete(&mut self) {
        self.with_selected(|store, id| store.remove(id));
    }

    fn with_selected<T>(&mut self, f: impl FnOnce(&tq_core::TaskStore, &str) -> tq_core::Result<T>) {
        let Some(task) = self.selected_task() else {
            return;
        };
        let id = task.id.clone();
        let lane = self.current_lane().to_string();
        let result = task_store_for(&lane).and_then(|store| f(&store, &id));
        match result {
            Ok(_) => self.set_status(format!("{id} updated")),
            Err(e) => self.set_error(e),
        }
        let _ = self.refresh();
        self.clamp_rows();
    }
}
