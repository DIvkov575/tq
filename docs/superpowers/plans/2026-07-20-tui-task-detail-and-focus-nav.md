# TUI Task Detail Popup + Tab-Into-Lane-Bar Focus Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user press `Enter` on a selected task to see its full (wrapped) title and notes in a popup, and press `Tab` to move keyboard focus up to the project-lane bar so plain `h/l`/arrows switch projects there, then back to the board.

**Architecture:** Both features are new `App` state (`detail_open: bool`, `focus: Focus`) gated through the same precedence-chain pattern `tq-tui` already uses for `help_open`/`input.active` — a new `App` field, a toggle/open/close method, a branch in `main.rs`'s key-routing `if/else if` chain, and a branch in `ui.rs::draw`'s render chain. The task detail popup reuses the existing `modal_height_for` + `centered_rect` + `.scroll()` sizing pattern from the input modal (no new sizing logic). The lane-bar focus mode reuses the existing `prev_lane`/`next_lane` methods verbatim, only redirecting `h/l`/arrow keys to call them instead of `move_column`/`move_row` when focus is on the lane bar.

**Tech Stack:** Rust, `ratatui` 0.29 (features: `unstable-rendered-line-info`, already enabled), `crossterm` 0.28.

---

## Before you start

Confirmed while researching this plan (don't re-derive these):

- `tq-tui/src/ui.rs` currently ends at line 429, with the `App`/`ui.rs` state as: `App` has `help_open: bool` (no `detail_open`, no `focus` yet). `ui.rs::draw` checks `app.help_open` then `app.input.active`. `ui.rs::contextual_help` checks `app.input.active` first, then builds from `current_column()`/`tasks_in()`.
- `crossterm::event::KeyCode::Tab` exists (confirmed in the vendored `crossterm-0.28.1` source, `src/event.rs:1033`) — no feature flag needed, it's a plain enum variant.
- `Task` (in `tq-core/src/task.rs`) already has `pub notes: String` alongside `pub title: String` — no `tq-core` changes needed, Task 1 just displays a field that's already there.
- `App::column_label(s: Status) -> &'static str` is a free function in `app.rs` (not a method), already imported into `ui.rs` via `use crate::app::{column_label, App, COLUMNS};` — reusable as-is for the detail popup's title.
- The existing `modal_height_for(text: &str, width: u16) -> u16` in `ui.rs` is fully generic (not input-modal-specific despite living next to `draw_input_modal`) — Task 1 below adds a second caller, no changes to `modal_height_for` itself.
- `draw_lane_bar`'s current styling: selected lane is `Style::default().fg(Color::Black).bg(Color::Cyan).add_modifier(Modifier::BOLD)`; unselected lanes are `Style::default().fg(Color::Gray)`. Task 2 changes only these two `Style` values when `app.focus == Focus::LaneBar`, not the surrounding layout — the lane bar's row stays `Constraint::Length(1)` in `draw`'s root layout, unchanged.

## Task 1: Task detail popup (`Enter` to view full task)

**Files:**
- Modify: `tq-tui/src/app.rs` (add `detail_open` field + `open_task_detail`/`close_task_detail` methods, extend test module)
- Modify: `tq-tui/src/main.rs` (route `Enter`/`Esc` while detail is open; bind `Enter` in normal mode)
- Modify: `tq-tui/src/ui.rs` (new `draw_task_detail`, wire into `draw` and `contextual_help`, extend test module)

- [ ] **Step 1: Write the failing tests for `open_task_detail`/`close_task_detail`**

Add to the existing `#[cfg(test)] mod tests` block at the bottom of `tq-tui/src/app.rs` (the one with `minimal_app()` and `toggle_help_flips_state`):

```rust
    fn app_with_task(status: Status) -> App {
        let mut task = Task::new("t", "");
        task.status = status;
        let mut app = minimal_app();
        app.tasks = vec![task];
        app
    }

    #[test]
    fn open_task_detail_opens_when_task_selected() {
        let mut app = app_with_task(Status::Queued);
        assert!(!app.detail_open);
        app.open_task_detail();
        assert!(app.detail_open);
    }

    #[test]
    fn open_task_detail_noop_when_column_empty() {
        let mut app = minimal_app();
        app.open_task_detail();
        assert!(!app.detail_open);
    }

    #[test]
    fn close_task_detail_closes() {
        let mut app = app_with_task(Status::Queued);
        app.open_task_detail();
        assert!(app.detail_open);
        app.close_task_detail();
        assert!(!app.detail_open);
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cargo test -p tq-tui open_task_detail`
Expected: compile error — `App` has no field `detail_open` and no method `open_task_detail`/`close_task_detail`.

- [ ] **Step 3: Add `detail_open` field and the two methods to `App`**

In `tq-tui/src/app.rs`, add `pub detail_open: bool,` to the `App` struct, immediately after `pub help_open: bool,`:

```rust
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
    pub detail_open: bool,
    pub should_quit: bool,
}
```

Update `App::load` to initialize it (add `detail_open: false,` right after `help_open: false,`):

```rust
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
            detail_open: false,
            should_quit: false,
        };
```

Update `minimal_app()` in the test module (used by `toggle_help_flips_state` and the new tests above) the same way — add `detail_open: false,` after `help_open: false,`:

```rust
    fn minimal_app() -> App {
        App {
            lanes: vec!["_unassigned".to_string()],
            lane_idx: 0,
            tasks: Vec::new(),
            column_idx: 0,
            row_idx: [0; 4],
            status_message: String::new(),
            input: InputState::default(),
            pending_project_name: String::new(),
            help_open: false,
            detail_open: false,
            should_quit: false,
        }
    }
```

Add the two methods next to `toggle_help` in `impl App`:

```rust
    pub fn open_task_detail(&mut self) {
        if self.selected_task().is_some() {
            self.detail_open = true;
        }
    }

    pub fn close_task_detail(&mut self) {
        self.detail_open = false;
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cargo test -p tq-tui open_task_detail close_task_detail`
Expected: all 3 new tests pass.

- [ ] **Step 5: Run the full `app.rs` test suite to check nothing broke**

Run: `cargo test -p tq-tui --lib app::tests`
Expected: all pass (the pre-existing `toggle_help_flips_state` plus the 3 new tests).

- [ ] **Step 6: Wire `detail_open` into `main.rs`'s key-routing chain**

In `tq-tui/src/main.rs`, the `run()` function currently has:

```rust
                if app.help_open {
                    handle_help_key(app, key.code);
                } else if app.input.active {
                    handle_input_key(app, key.code);
                } else {
                    handle_normal_key(app, key.code);
                }
```

Change to insert a `detail_open` branch between `help_open` and `input.active` (matching the precedence order used by `draw`'s render chain, wired in Step 8 below — help wins over everything, detail wins over input/normal):

```rust
                if app.help_open {
                    handle_help_key(app, key.code);
                } else if app.detail_open {
                    handle_detail_key(app, key.code);
                } else if app.input.active {
                    handle_input_key(app, key.code);
                } else {
                    handle_normal_key(app, key.code);
                }
```

Add `handle_detail_key` next to `handle_help_key`:

```rust
fn handle_detail_key(app: &mut App, code: KeyCode) {
    match code {
        KeyCode::Enter | KeyCode::Esc => app.close_task_detail(),
        _ => {}
    }
}
```

Add `Enter` to `handle_normal_key`'s match arms (anywhere among the other `Char`/`KeyCode` arms):

```rust
        KeyCode::Enter => app.open_task_detail(),
```

- [ ] **Step 7: Run a build to confirm `main.rs` compiles**

Run: `cargo check -p tq-tui`
Expected: `Finished` with no errors.

- [ ] **Step 8: Write the failing test for `draw_task_detail`'s content**

Add to the existing `#[cfg(test)] mod tests` block at the bottom of `tq-tui/src/ui.rs` (the one with `test_app`, `task_with_status`, etc.):

```rust
    #[test]
    fn draw_task_detail_shows_title_and_notes() {
        let backend = TestBackend::new(80, 24);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut task = Task::new("a very specific task title", "some helpful notes");
        task.status = Status::Queued;
        let mut app = test_app(vec![task], 0);
        app.detail_open = true;
        terminal.draw(|f| draw(f, &app)).unwrap();
        let buffer = terminal.backend().buffer();
        let rendered: String = buffer.content().iter().map(|cell| cell.symbol()).collect();
        assert!(rendered.contains("a very specific"), "expected title to be visible, got: {rendered}");
        assert!(rendered.contains("some helpful"), "expected notes to be visible, got: {rendered}");
    }

    #[test]
    fn draw_task_detail_omits_notes_line_when_empty() {
        let backend = TestBackend::new(80, 24);
        let mut terminal = Terminal::new(backend).unwrap();
        let task = Task::new("bare title", "");
        let mut app = test_app(vec![task], 0);
        app.detail_open = true;
        terminal.draw(|f| draw(f, &app)).unwrap();
        let buffer = terminal.backend().buffer();
        let rendered: String = buffer.content().iter().map(|cell| cell.symbol()).collect();
        assert!(!rendered.contains("notes:"), "expected no notes line for empty notes, got: {rendered}");
    }
```

(`Task::new(title, notes)` already exists per `tq-core/src/task.rs`; `TestBackend`/`Terminal` are already imported in this test module from the prior `draw_does_not_panic_with_help_open` test.)

- [ ] **Step 9: Run the tests to verify they fail**

Run: `cargo test -p tq-tui draw_task_detail`
Expected: compile error, `cannot find function 'draw_task_detail' in this scope` (or `app.detail_open` field error if Task 1's earlier steps somehow didn't land in this file — they don't touch `ui.rs`, so this should be purely the missing function).

- [ ] **Step 10: Implement `draw_task_detail` and wire it into `draw`/`contextual_help`**

In `tq-tui/src/ui.rs`, add a new function near `draw_input_modal`:

```rust
fn draw_task_detail(frame: &mut Frame, app: &App) {
    let Some(task) = app.selected_task() else {
        return;
    };

    let mut body = task.title.clone();
    if !task.notes.is_empty() {
        body.push_str("\n\n");
        body.push_str("notes: ");
        body.push_str(&task.notes);
    }
    body.push_str("\n\nEnter or Esc to close");

    const MODAL_WIDTH_PCT: u16 = 60;
    let probe = centered_rect(MODAL_WIDTH_PCT, 1, frame.area());
    let inner_width = probe.width.saturating_sub(2);

    let height = modal_height_for(&body, inner_width);
    let area = centered_rect(MODAL_WIDTH_PCT, height, frame.area());
    frame.render_widget(Clear, area);

    let title = format!(" {} task ", column_label(task.status));
    let block = Block::default()
        .title(title)
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Cyan));

    let total_lines = Paragraph::new(body.as_str())
        .wrap(Wrap { trim: false })
        .line_count(inner_width) as u16;
    let scroll_y = total_lines.saturating_sub(height);

    let paragraph = Paragraph::new(body)
        .block(block)
        .wrap(Wrap { trim: false })
        .scroll((scroll_y, 0));
    frame.render_widget(paragraph, area);
}
```

Update `draw` to check `detail_open` between `help_open` and `input.active`:

```rust
pub fn draw(frame: &mut Frame, app: &App) {
    let root = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1),
            Constraint::Min(3),
            Constraint::Length(1),
        ])
        .split(frame.area());

    draw_lane_bar(frame, app, root[0]);
    draw_columns(frame, app, root[1]);
    draw_status_bar(frame, app, root[2]);

    if app.help_open {
        draw_help_overlay(frame);
    } else if app.detail_open {
        draw_task_detail(frame, app);
    } else if app.input.active {
        draw_input_modal(frame, app);
    }
}
```

Update `contextual_help` to add a `detail_open` early-return, checked right after the existing `input.active` check (before the `let mut parts = ...` line):

```rust
fn contextual_help(app: &App) -> String {
    if app.input.active {
        return "Enter submit  Esc cancel".to_string();
    }
    if app.detail_open {
        return "Enter/Esc to close".to_string();
    }

    let mut parts = vec!["j/k row".to_string(), "h/l col".to_string(), "J/K project".to_string()];
    // ... rest unchanged
```

(Only the two new lines are added; everything below `let mut parts = ...` in the current function stays exactly as-is.)

- [ ] **Step 11: Run the tests to verify they pass**

Run: `cargo test -p tq-tui draw_task_detail`
Expected: both new tests pass.

- [ ] **Step 12: Update `test_app` callers' struct literal for `detail_open` — check if needed**

`test_app` in `ui.rs`'s test module builds an `App` struct literal directly. Since Task 1 Step 3 added `detail_open` to the `App` struct, `test_app`'s literal (and any other direct `App { ... }` literal in `ui.rs`) will fail to compile without a `detail_open: false,` field. Add it to `test_app` right after `help_open: false,`:

```rust
    fn test_app(lane_tasks: Vec<Task>, column_idx: usize) -> App {
        App {
            lanes: vec!["_unassigned".to_string()],
            lane_idx: 0,
            tasks: lane_tasks,
            column_idx,
            row_idx: [0; 4],
            status_message: String::new(),
            input: InputState::default(),
            pending_project_name: String::new(),
            help_open: false,
            detail_open: false,
            should_quit: false,
        }
    }
```

- [ ] **Step 13: Run the full `tq-tui` test suite**

Run: `cargo test -p tq-tui`
Expected: all tests pass (previous 17 + 3 in `app.rs` + 2 in `ui.rs` = 22 total).

- [ ] **Step 14: Update the help overlay's static text to mention `Enter`**

In `tq-tui/src/ui.rs`'s `help_overlay_text()`, add an `Enter` line under the `Navigate` section (right after the `J/K` line):

```rust
fn help_overlay_text() -> String {
    [
        "Navigate",
        "  h/l · ←/→   move column",
        "  j/k · ↑/↓   move row",
        "  J/K         switch project",
        "  Enter       view task detail",
        "",
        "Task actions",
        "  a  add       e  edit",
        "  s  start     c  complete",
        "  H  hold      r  release",
        "  R  requeue   d  delete",
        "",
        "Project",
        "  n  new project",
        "",
        "Quit",
        "  q  quit",
        "",
        "? or Esc to close",
    ]
    .join("\n")
}
```

- [ ] **Step 15: Run the full test suite once more (the overlay content changed)**

Run: `cargo test -p tq-tui help_overlay`
Expected: `help_overlay_lists_every_key` and `help_overlay_renders_without_clipping_last_line` both still pass (the added line doesn't remove any of the previously-required substrings, and the overlay's height is still derived dynamically from `text.lines().count()`, so the extra line doesn't reintroduce the old clipping bug).

- [ ] **Step 16: Commit**

```bash
git add tq-tui/src/app.rs tq-tui/src/main.rs tq-tui/src/ui.rs
git commit -m "tq-tui: add Enter-to-view task detail popup"
```

## Task 2: Tab-into-lane-bar focus navigation

**Files:**
- Modify: `tq-tui/src/app.rs` (add `Focus` enum, `focus` field, `toggle_focus` method, extend test module)
- Modify: `tq-tui/src/main.rs` (bind `Tab`; branch `h/l`/arrows/`Enter` on `app.focus` in `handle_normal_key`)
- Modify: `tq-tui/src/ui.rs` (focus-aware `draw_lane_bar` styling, `contextual_help` branch, extend test module)
- Modify: `README.md` (mention `Tab` and `Enter` in the keys line)

- [ ] **Step 1: Write the failing test for `toggle_focus`**

Add to the `#[cfg(test)] mod tests` block in `tq-tui/src/app.rs`:

```rust
    #[test]
    fn toggle_focus_flips_between_board_and_lane_bar() {
        let mut app = minimal_app();
        assert_eq!(app.focus, Focus::Board);
        app.toggle_focus();
        assert_eq!(app.focus, Focus::LaneBar);
        app.toggle_focus();
        assert_eq!(app.focus, Focus::Board);
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cargo test -p tq-tui toggle_focus`
Expected: compile error — no `Focus` type, no `app.focus` field, no `toggle_focus` method.

- [ ] **Step 3: Add the `Focus` enum, `focus` field, and `toggle_focus` method**

In `tq-tui/src/app.rs`, add the enum near the top, right after the existing `InputPurpose` enum:

```rust
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub enum Focus {
    #[default]
    Board,
    LaneBar,
}
```

Add `pub focus: Focus,` to the `App` struct, right after `pub detail_open: bool,`:

```rust
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
    pub detail_open: bool,
    pub focus: Focus,
    pub should_quit: bool,
}
```

Update `App::load` to initialize it (add `focus: Focus::Board,` after `detail_open: false,`):

```rust
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
            detail_open: false,
            focus: Focus::Board,
            should_quit: false,
        };
```

Update `minimal_app()` in the test module the same way (add `focus: Focus::Board,` after `detail_open: false,`):

```rust
    fn minimal_app() -> App {
        App {
            lanes: vec!["_unassigned".to_string()],
            lane_idx: 0,
            tasks: Vec::new(),
            column_idx: 0,
            row_idx: [0; 4],
            status_message: String::new(),
            input: InputState::default(),
            pending_project_name: String::new(),
            help_open: false,
            detail_open: false,
            focus: Focus::Board,
            should_quit: false,
        }
    }
```

`app_with_task` (added in Task 1 Step 1) calls `minimal_app()` internally, so it doesn't need its own edit.

Add `toggle_focus` next to `toggle_help`:

```rust
    pub fn toggle_focus(&mut self) {
        self.focus = match self.focus {
            Focus::Board => Focus::LaneBar,
            Focus::LaneBar => Focus::Board,
        };
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cargo test -p tq-tui toggle_focus`
Expected: passes.

- [ ] **Step 5: Run the full `app.rs` test suite**

Run: `cargo test -p tq-tui --lib app::tests`
Expected: all pass (previous tests + `toggle_focus_flips_between_board_and_lane_bar`).

- [ ] **Step 6: Wire `Tab` and focus-aware directional keys into `main.rs`**

In `tq-tui/src/main.rs`, add `Focus` to the `use app::App;` import line:

```rust
use app::{App, Focus};
```

Replace `handle_normal_key`'s body. Current body:

```rust
fn handle_normal_key(app: &mut App, code: KeyCode) {
    match code {
        KeyCode::Char('q') => app.should_quit = true,
        KeyCode::Char('j') | KeyCode::Down => app.move_row(1),
        KeyCode::Char('k') | KeyCode::Up => app.move_row(-1),
        KeyCode::Char('l') | KeyCode::Right => app.move_column(1),
        KeyCode::Char('h') | KeyCode::Left => app.move_column(-1),
        KeyCode::Char('J') => app.next_lane(),
        KeyCode::Char('K') => app.prev_lane(),
        KeyCode::Char('a') => app.open_add_task(),
        KeyCode::Char('e') => app.open_edit_title(),
        KeyCode::Char('s') => app.act_start(),
        KeyCode::Char('c') => app.act_complete(),
        KeyCode::Char('H') => app.act_hold(),
        KeyCode::Char('r') => app.act_release(),
        KeyCode::Char('R') => app.act_requeue(),
        KeyCode::Char('d') => app.act_delete(),
        KeyCode::Char('n') => app.open_new_project(),
        KeyCode::Char('?') => app.toggle_help(),
        KeyCode::Enter => app.open_task_detail(),
        _ => {}
    }
}
```

New body — the global/action keys stay a flat match; only the directional keys (`h/l`/arrows) and `Enter` branch on `app.focus` first:

```rust
fn handle_normal_key(app: &mut App, code: KeyCode) {
    match code {
        KeyCode::Tab => app.toggle_focus(),
        KeyCode::Char('h') | KeyCode::Left => match app.focus {
            Focus::Board => app.move_column(-1),
            Focus::LaneBar => app.prev_lane(),
        },
        KeyCode::Char('l') | KeyCode::Right => match app.focus {
            Focus::Board => app.move_column(1),
            Focus::LaneBar => app.next_lane(),
        },
        KeyCode::Char('j') | KeyCode::Down => {
            if app.focus == Focus::Board {
                app.move_row(1);
            }
        }
        KeyCode::Char('k') | KeyCode::Up => {
            if app.focus == Focus::Board {
                app.move_row(-1);
            }
        }
        KeyCode::Enter => match app.focus {
            Focus::Board => app.open_task_detail(),
            Focus::LaneBar => app.focus = Focus::Board,
        },
        KeyCode::Esc if app.focus == Focus::LaneBar => app.focus = Focus::Board,
        KeyCode::Char('q') => app.should_quit = true,
        KeyCode::Char('J') => app.next_lane(),
        KeyCode::Char('K') => app.prev_lane(),
        KeyCode::Char('a') => app.open_add_task(),
        KeyCode::Char('e') => app.open_edit_title(),
        KeyCode::Char('s') => app.act_start(),
        KeyCode::Char('c') => app.act_complete(),
        KeyCode::Char('H') => app.act_hold(),
        KeyCode::Char('r') => app.act_release(),
        KeyCode::Char('R') => app.act_requeue(),
        KeyCode::Char('d') => app.act_delete(),
        KeyCode::Char('n') => app.open_new_project(),
        KeyCode::Char('?') => app.toggle_help(),
        _ => {}
    }
}
```

Note: this reaches `Focus::LaneBar` handling of `h/l`/`Enter`/`Esc` only when `handle_normal_key` is called at all — which per the existing precedence chain in `run()` only happens when `help_open`, `detail_open`, and `input.active` are all false. `Esc` with no `if app.focus == Focus::LaneBar` guard would otherwise silently do nothing in `Focus::Board` (falls through to `_ => {}`), which matches today's behavior (there was no `Esc` binding in normal/board mode before this change either).

- [ ] **Step 7: Run a build to confirm `main.rs` compiles**

Run: `cargo check -p tq-tui`
Expected: `Finished` with no errors.

- [ ] **Step 8: No unit test for this step — manual verification only**

The `h/l`/`j/k`/`Enter` focus-branching logic added in Step 6 lives entirely in `main.rs::handle_normal_key`, a free function operating on `crossterm::event::KeyCode` values with no unit-test seam (it's not exposed as a library, and driving it requires a real/fake terminal event loop). This matches the existing codebase precedent: `handle_help_key` and `handle_input_key` also have zero `#[cfg(test)]` coverage today. `Focus`'s state machine itself (`toggle_focus`) is already covered by Step 1's test — what Step 6 added on top is pure key-to-method dispatch, verified manually in Step 9 below.

- [ ] **Step 9: Manually verify the key routing**

Run: `cargo build -p tq-tui --release && ./target/release/tqctl-tui`

In the running TUI:
1. Press `Tab`. Confirm the lane bar's appearance changes (this will visually confirm once Step 11 below lands the styling change — if testing before that step, skip the visual check and just confirm no crash).
2. With focus on the lane bar, press `h`/`l` and confirm the selected lane changes (visible via the lane bar highlighting move) and the task columns do NOT change.
3. Press `j`/`k` while focus is on the lane bar and confirm nothing happens (no panic, no visible change).
4. Press `Enter` while focus is on the lane bar and confirm focus returns to the board (subsequent `h/l` now move columns again).
5. Press `Tab` again, then `Esc`, and confirm focus returns to the board the same way.
6. Back on the board, confirm `J`/`K` still switch lanes directly (unchanged shortcut), and `h/l`/`j/k` move columns/rows as before.
7. Press `q` to quit.

This is a manual smoke check because `main.rs`'s key-handling functions operate on `crossterm::event::KeyCode` and aren't unit-testable without a fake terminal driving real key events through `run()` — the existing codebase doesn't have that kind of test for its other key handlers either (`handle_help_key`, `handle_input_key`), so this plan follows the same precedent rather than introducing a new testing seam for one feature.

- [ ] **Step 10: Write the failing test for lane-bar focus styling**

Add to the `#[cfg(test)] mod tests` block in `tq-tui/src/ui.rs`:

```rust
    #[test]
    fn draw_lane_bar_uses_cyan_text_when_lane_bar_focused() {
        let backend = TestBackend::new(80, 24);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = test_app(vec![], 0);
        app.lanes = vec!["proj-a".to_string(), "proj-b".to_string()];
        app.focus = crate::app::Focus::LaneBar;
        terminal.draw(|f| draw(f, &app)).unwrap();
        let buffer = terminal.backend().buffer();
        // The unselected lane ("proj-b", lane_idx stays 0 so "proj-a" is selected)
        // must render with cyan foreground when the lane bar has focus.
        let found_cyan_unselected = buffer.content().iter().any(|cell| {
            cell.symbol().contains('b') && cell.fg == Color::Cyan
        });
        assert!(found_cyan_unselected, "expected unselected lane text to be cyan when lane bar is focused");
    }

    #[test]
    fn draw_lane_bar_uses_gray_text_when_board_focused() {
        let backend = TestBackend::new(80, 24);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = test_app(vec![], 0);
        app.lanes = vec!["proj-a".to_string(), "proj-b".to_string()];
        terminal.draw(|f| draw(f, &app)).unwrap();
        let buffer = terminal.backend().buffer();
        let found_gray_unselected = buffer.content().iter().any(|cell| {
            cell.symbol().contains('b') && cell.fg == Color::Gray
        });
        assert!(found_gray_unselected, "expected unselected lane text to be gray when board is focused (default)");
    }
```

- [ ] **Step 11: Run the tests to verify they fail**

Run: `cargo test -p tq-tui draw_lane_bar_uses`
Expected: `draw_lane_bar_uses_cyan_text_when_lane_bar_focused` fails (assertion false — `draw_lane_bar` doesn't check focus yet, so unselected lanes are always gray). `draw_lane_bar_uses_gray_text_when_board_focused` should already pass (it's asserting today's existing default behavior) — that's fine, it's a regression guard for Step 12's change, not a new-behavior test.

- [ ] **Step 12: Implement focus-aware styling in `draw_lane_bar`**

Replace `draw_lane_bar` in `tq-tui/src/ui.rs`:

```rust
fn draw_lane_bar(frame: &mut Frame, app: &App, area: Rect) {
    let lane_bar_focused = app.focus == Focus::LaneBar;
    let mut spans = Vec::new();
    for (i, lane) in app.lanes.iter().enumerate() {
        let style = if i == app.lane_idx {
            let bg = if lane_bar_focused { Color::Green } else { Color::Cyan };
            Style::default().fg(Color::Black).bg(bg).add_modifier(Modifier::BOLD)
        } else {
            let fg = if lane_bar_focused { Color::Cyan } else { Color::Gray };
            Style::default().fg(fg)
        };
        spans.push(Span::styled(format!(" {lane} "), style));
    }
    frame.render_widget(Line::from(spans), area);
}
```

Add `Focus` to the `crate::app` import at the top of `ui.rs`:

```rust
use crate::app::{column_label, App, Focus, COLUMNS};
```

- [ ] **Step 13: Run the tests to verify they pass**

Run: `cargo test -p tq-tui draw_lane_bar_uses`
Expected: both tests pass.

- [ ] **Step 14: Write the failing test for `contextual_help`'s lane-bar branch**

Add to the `#[cfg(test)] mod tests` block in `tq-tui/src/ui.rs`:

```rust
    #[test]
    fn contextual_help_for_lane_bar_focus() {
        let mut app = test_app(vec![], 0);
        app.focus = crate::app::Focus::LaneBar;
        let help = contextual_help(&app);
        assert!(help.contains("switch project"));
        assert!(help.contains("back to board"));
        assert!(!help.contains("a add"));
    }
```

- [ ] **Step 15: Run the test to verify it fails**

Run: `cargo test -p tq-tui contextual_help_for_lane_bar_focus`
Expected: fails — `contextual_help` doesn't check `app.focus` yet, so it falls through to the `Board`-oriented logic which includes `"a add"`.

- [ ] **Step 16: Add the `Focus::LaneBar` branch to `contextual_help`**

In `tq-tui/src/ui.rs`, `contextual_help` currently starts with (after Task 1 Step 10 landed the `detail_open` check):

```rust
fn contextual_help(app: &App) -> String {
    if app.input.active {
        return "Enter submit  Esc cancel".to_string();
    }
    if app.detail_open {
        return "Enter/Esc to close".to_string();
    }

    let mut parts = vec!["j/k row".to_string(), "h/l col".to_string(), "J/K project".to_string()];
    // ...
```

Add a third early-return, after the `detail_open` check:

```rust
fn contextual_help(app: &App) -> String {
    if app.input.active {
        return "Enter submit  Esc cancel".to_string();
    }
    if app.detail_open {
        return "Enter/Esc to close".to_string();
    }
    if app.focus == Focus::LaneBar {
        return "h/l · ←/→ switch project  Enter/Esc back to board  q quit".to_string();
    }

    let mut parts = vec!["j/k row".to_string(), "h/l col".to_string(), "J/K project".to_string()];
    // ... rest unchanged
```

- [ ] **Step 17: Run the test to verify it passes**

Run: `cargo test -p tq-tui contextual_help_for_lane_bar_focus`
Expected: passes.

- [ ] **Step 18: Update `test_app` for the new `focus` field**

`test_app` in `ui.rs`'s test module needs `focus: Focus::Board,` added to its struct literal (Task 2 Step 3 added `focus` to `App`):

```rust
    fn test_app(lane_tasks: Vec<Task>, column_idx: usize) -> App {
        App {
            lanes: vec!["_unassigned".to_string()],
            lane_idx: 0,
            tasks: lane_tasks,
            column_idx,
            row_idx: [0; 4],
            status_message: String::new(),
            input: InputState::default(),
            pending_project_name: String::new(),
            help_open: false,
            detail_open: false,
            focus: Focus::Board,
            should_quit: false,
        }
    }
```

- [ ] **Step 19: Run the full `tq-tui` test suite**

Run: `cargo test -p tq-tui`
Expected: all tests pass (22 from Task 1 + `toggle_focus_flips_between_board_and_lane_bar` + `draw_lane_bar_uses_cyan_text_when_lane_bar_focused` + `draw_lane_bar_uses_gray_text_when_board_focused` + `contextual_help_for_lane_bar_focus` = 26 total).

- [ ] **Step 20: Update the help overlay's static text to mention `Tab`**

In `tq-tui/src/ui.rs`'s `help_overlay_text()` (already modified in Task 1 Step 14 to include the `Enter` line), add a `Tab` line right after it:

```rust
fn help_overlay_text() -> String {
    [
        "Navigate",
        "  h/l · ←/→   move column",
        "  j/k · ↑/↓   move row",
        "  J/K         switch project",
        "  Tab         focus project bar",
        "  Enter       view task detail",
        "",
        "Task actions",
        "  a  add       e  edit",
        "  s  start     c  complete",
        "  H  hold      r  release",
        "  R  requeue   d  delete",
        "",
        "Project",
        "  n  new project",
        "",
        "Quit",
        "  q  quit",
        "",
        "? or Esc to close",
    ]
    .join("\n")
}
```

- [ ] **Step 21: Run the help overlay tests once more**

Run: `cargo test -p tq-tui help_overlay`
Expected: still passes (adding a line doesn't remove required substrings or reintroduce the clipping bug, since height is still derived from `text.lines().count()`).

- [ ] **Step 22: Update the README's keys line**

In `README.md`, the current text (lines 63-72) reads:

```
`ratatui`-based board: a lane bar across the top (switch projects with
`J`/`K`), four columns (QUEUED / RUNNING / HELD / COMPLETED) for the
selected lane, navigable with `h`/`j`/`k`/`l` or arrow keys. The TUI always
has full access — the held-locked restriction only applies to
`tqctl-restricted`.

Keys: `a` add task, `e` edit title, `s` start, `c` complete, `H` hold,
`r` release, `R` requeue, `d` delete, `n` register a new project, `?`
show all keybindings, `q` quit. The status bar at the bottom always shows
the keys usable right now for the focused column.
```

Change to:

```
`ratatui`-based board: a lane bar across the top (switch projects with
`J`/`K`, or press `Tab` to move focus there and switch with `h`/`l`/arrows,
`Enter` or `Esc` to return), four columns (QUEUED / RUNNING / HELD /
COMPLETED) for the selected lane, navigable with `h`/`j`/`k`/`l` or arrow
keys. The TUI always has full access — the held-locked restriction only
applies to `tqctl-restricted`.

Keys: `Enter` view full task detail, `a` add task, `e` edit title, `s`
start, `c` complete, `H` hold, `r` release, `R` requeue, `d` delete, `n`
register a new project, `?` show all keybindings, `q` quit. The status bar
at the bottom always shows the keys usable right now for the focused
column or bar.
```

- [ ] **Step 23: Run the full workspace test suite and build**

Run: `cargo test --workspace && cargo build --workspace --release`
Expected: everything passes and builds.

- [ ] **Step 24: Commit**

```bash
git add tq-tui/src/app.rs tq-tui/src/main.rs tq-tui/src/ui.rs README.md
git commit -m "tq-tui: add Tab-into-lane-bar focus navigation"
```

## Self-Review Notes

- **Spec coverage:** Spec Part 1 (task detail popup) → Task 1 (fields, methods, key routing, rendering, help-overlay/status-bar mentions). Spec Part 2 (Tab-into-lane-bar) → Task 2 (`Focus` enum, `toggle_focus`, directional-key branching, lane-bar styling, `contextual_help` branch, help-overlay/README mentions). Spec's precedence-order requirement (`help_open` → `detail_open` → `input.active` → normal) is implemented identically in both `main.rs`'s `run()` chain and `ui.rs`'s `draw()` chain, per the spec's explicit requirement that both match.
- **Type consistency:** `Focus::Board`/`Focus::LaneBar` are used identically across `app.rs` (definition, `toggle_focus`), `main.rs` (`handle_normal_key`'s match), and `ui.rs` (`draw_lane_bar`, `contextual_help`) — no renamed variants. `detail_open`/`open_task_detail`/`close_task_detail` names match between `app.rs`'s definition and `main.rs`'s call sites. Every `App { ... }` struct literal across both files' test modules (`minimal_app`, `test_app`) is updated in lockstep as each new field is introduced (Task 1 Step 3 & 12 for `detail_open`; Task 2 Step 3 & 18 for `focus`) — checked that no literal is missed, since a missed one would be a compile error surfaced immediately by the next `cargo test` step, not a silent gap.
- **Placeholder scan:** no TBD/TODO. Task 2 Step 8 explicitly walks through why a first-draft test didn't actually test anything meaningful, discards it, and states the real coverage strategy (manual verification in Step 9, consistent with the existing codebase's lack of unit tests for `main.rs`'s other key handlers) rather than leaving a vague "add tests for key routing" instruction.
