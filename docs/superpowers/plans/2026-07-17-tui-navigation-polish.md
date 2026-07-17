# TUI Navigation/Bindings Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `tq-tui` ratatui board's input modal wrap long text instead of overflowing, replace the static 96-character status-bar help string with a line that only shows keys valid for the current context, and add a `?` overlay listing every keybinding at once.

**Architecture:** All changes live in `tq-tui/src/app.rs` (new `App.help_open` field + toggle logic), `tq-tui/src/main.rs` (route `?` key + gate normal-mode keys while the overlay is open), and `tq-tui/src/ui.rs` (wrap-aware input modal sizing, a new `contextual_help()` function feeding the status bar, and a new `draw_help_overlay()`). No changes to `tq-core` or the CLI. No changes to the actual key-to-action mapping.

**Tech Stack:** Rust, `ratatui` 0.29 (needs the `unstable-rendered-line-info` cargo feature enabled for `Paragraph::line_count`), `crossterm` 0.28.

---

## Before you start

Confirmed while researching this plan (don't re-derive these):

- `ratatui::widgets::Paragraph::line_count(width: u16) -> usize` exists in 0.29 but is gated behind the `unstable-rendered-line-info` cargo feature on the `ratatui` dependency. Task 1 turns this feature on.
- `ratatui::backend::TestBackend` is available unconditionally (no feature needed) — used for the rendering tests in Tasks 1-3.
- The input modal's `centered_rect(60, height, area)` on a `Rect { width: 80, height: 24 }` test area produces an outer rect of `width: 48`, so the `Paragraph`'s wrap width (inner width, after the 1-cell border on each side) is **46**. All `line_count` calls and test fixtures below use width `46`.
- Empirically verified wrap boundaries at width 46 (via `Paragraph::new(text).wrap(Wrap { trim: false }).line_count(46)`): a 46-char string wraps to 1 line, 47 chars to 2 lines, 368 chars to 8 lines, 369 chars to 9 lines. Task 1's tests rely on exactly these numbers.

## Task 1: Wrap text in the input modal

**Files:**
- Modify: `tq-tui/Cargo.toml`
- Modify: `tq-tui/src/ui.rs:105-134` (`draw_input_modal`, `centered_rect`)
- Test: `tq-tui/src/ui.rs` (new `#[cfg(test)] mod tests` block at the end of the file)

- [ ] **Step 1: Enable the ratatui unstable feature needed for `line_count`**

In `tq-tui/Cargo.toml`, change:

```toml
ratatui = "0.29"
```

to:

```toml
ratatui = { version = "0.29", features = ["unstable-rendered-line-info"] }
```

- [ ] **Step 2: Run a build to confirm the feature resolves**

Run: `cargo check -p tq-tui`
Expected: `Finished` with no errors (this only changes what's exposed, not behavior, so nothing else should break yet).

- [ ] **Step 3: Write the failing tests for a new `modal_height_for` helper**

Add this at the bottom of `tq-tui/src/ui.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn modal_height_for_empty_text_is_one_line() {
        assert_eq!(modal_height_for("", 46), 1);
    }

    #[test]
    fn modal_height_for_short_text_is_one_line() {
        assert_eq!(modal_height_for("short title", 46), 1);
    }

    #[test]
    fn modal_height_for_text_at_exact_width_is_one_line() {
        let text = "x".repeat(46);
        assert_eq!(modal_height_for(&text, 46), 1);
    }

    #[test]
    fn modal_height_for_text_one_over_width_wraps_to_two_lines() {
        let text = "x".repeat(47);
        assert_eq!(modal_height_for(&text, 46), 2);
    }

    #[test]
    fn modal_height_for_very_long_text_caps_at_max() {
        // 369 chars wraps to 9 lines unwrapped; must be capped at 8.
        let text = "x".repeat(369);
        assert_eq!(modal_height_for(&text, 46), 8);
    }

    #[test]
    fn modal_height_for_text_at_cap_boundary_is_uncapped() {
        // 368 chars wraps to exactly 8 lines; the cap must not kick in early.
        let text = "x".repeat(368);
        assert_eq!(modal_height_for(&text, 46), 8);
    }
}
```

- [ ] **Step 4: Run the tests to verify they fail (function doesn't exist yet)**

Run: `cargo test -p tq-tui modal_height_for`
Expected: compile error, `cannot find function 'modal_height_for' in this scope`.

- [ ] **Step 5: Implement `modal_height_for` and wire it into `draw_input_modal`**

Replace the current `draw_input_modal` and `centered_rect` in `tq-tui/src/ui.rs` (lines 105-134) with:

```rust
/// Max modal height in text lines, so a very long pasted title can't fill the screen.
const MAX_INPUT_MODAL_LINES: u16 = 8;

/// Number of wrapped lines `text` occupies at `width` columns, clamped to
/// `[1, MAX_INPUT_MODAL_LINES]`.
fn modal_height_for(text: &str, width: u16) -> u16 {
    let lines = Paragraph::new(text)
        .wrap(Wrap { trim: false })
        .line_count(width) as u16;
    lines.max(1).min(MAX_INPUT_MODAL_LINES)
}

fn draw_input_modal(frame: &mut Frame, app: &App) {
    const MODAL_WIDTH_PCT: u16 = 60;
    // centered_rect's horizontal split (which determines width) only depends
    // on width_pct and the frame's full width, not on height — ratatui's
    // Percentage constraint solver doesn't round the same as naive
    // `width * pct / 100` at every terminal width, so probe the real width
    // with a throwaway height instead of recomputing the percentage by hand.
    let probe = centered_rect(MODAL_WIDTH_PCT, 1, frame.area());
    let inner_width = probe.width.saturating_sub(2);

    let height = modal_height_for(&app.input.buffer, inner_width);
    let area = centered_rect(MODAL_WIDTH_PCT, height, frame.area());
    frame.render_widget(Clear, area);

    let block = Block::default()
        .title(app.input.prompt.as_str())
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Cyan));

    let total_lines = Paragraph::new(app.input.buffer.as_str())
        .wrap(Wrap { trim: false })
        .line_count(inner_width) as u16;
    let scroll_y = total_lines.saturating_sub(height);

    let text = Paragraph::new(app.input.buffer.as_str())
        .block(block)
        .wrap(Wrap { trim: false })
        .scroll((scroll_y, 0));
    frame.render_widget(text, area);
}

fn centered_rect(width_pct: u16, height: u16, area: Rect) -> Rect {
    let vertical = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage(50 - height.min(50) / 2),
            Constraint::Length(height + 2),
            Constraint::Min(0),
        ])
        .split(area);
    let horizontal = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage((100 - width_pct) / 2),
            Constraint::Percentage(width_pct),
            Constraint::Percentage((100 - width_pct) / 2),
        ])
        .split(vertical[1]);
    horizontal[1]
}
```

Add `Wrap` to the existing `ratatui::widgets` import at the top of the file:

```rust
use ratatui::widgets::{Block, Borders, Clear, List, ListItem, Paragraph, Wrap};
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cargo test -p tq-tui modal_height_for`
Expected: all 6 tests pass.

Task 1's `modal_height_for` is a pure function and is fully covered by the unit tests in Step 3 — no rendering/`TestBackend` test is needed yet. A full `draw()` rendering smoke test needs `App::help_open`, which doesn't exist until Task 3; that test is added in Task 3 Step 10 instead, once `App` is stable.

- [ ] **Step 7: Commit**

```bash
git add tq-tui/Cargo.toml tq-tui/src/ui.rs Cargo.lock
git commit -m "tq-tui: wrap long text in the input modal instead of overflowing"
```

## Task 2: Contextual single-line status bar

**Files:**
- Modify: `tq-tui/src/ui.rs:95-103` (`draw_status_bar`)
- Test: `tq-tui/src/ui.rs` (extend the `mod tests` block added in Task 1)

- [ ] **Step 1: Write the failing tests**

Add to the `mod tests` block in `tq-tui/src/ui.rs`:

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
            should_quit: false,
        }
    }

    fn task_with_status(status: Status) -> Task {
        let mut t = Task::new("t", "");
        t.status = status;
        t
    }

    #[test]
    fn contextual_help_for_queued_column_with_task() {
        let app = test_app(vec![task_with_status(Status::Queued)], 0);
        let help = contextual_help(&app);
        assert!(help.contains("s start"));
        assert!(help.contains("H hold"));
        assert!(!help.contains("c complete"));
        assert!(!help.contains("r release"));
        assert!(!help.contains("R requeue"));
    }

    #[test]
    fn contextual_help_for_running_column_with_task() {
        let app = test_app(vec![task_with_status(Status::Running)], 1);
        let help = contextual_help(&app);
        assert!(help.contains("c complete"));
        assert!(help.contains("R requeue"));
        assert!(!help.contains("s start"));
        assert!(!help.contains("H hold"));
    }

    #[test]
    fn contextual_help_for_held_column_with_task() {
        let app = test_app(vec![task_with_status(Status::Held)], 2);
        let help = contextual_help(&app);
        assert!(help.contains("r release"));
        assert!(!help.contains("H hold"));
        assert!(!help.contains("c complete"));
    }

    #[test]
    fn contextual_help_for_completed_column_with_task() {
        let app = test_app(vec![task_with_status(Status::Completed)], 3);
        let help = contextual_help(&app);
        assert!(help.contains("e edit"));
        assert!(help.contains("d delete"));
        assert!(!help.contains("s start"));
        assert!(!help.contains("c complete"));
        assert!(!help.contains("H hold"));
        assert!(!help.contains("r release"));
        assert!(!help.contains("R requeue"));
    }

    #[test]
    fn contextual_help_for_empty_column_hides_task_actions() {
        let app = test_app(vec![], 0);
        let help = contextual_help(&app);
        assert!(help.contains("a add"));
        assert!(!help.contains("e edit"));
        assert!(!help.contains("s start"));
        assert!(!help.contains("d delete"));
    }

    #[test]
    fn contextual_help_always_includes_global_keys() {
        let app = test_app(vec![], 0);
        let help = contextual_help(&app);
        assert!(help.contains("j/k row"));
        assert!(help.contains("h/l col"));
        assert!(help.contains("J/K project"));
        assert!(help.contains("n new-project"));
        assert!(help.contains('?'));
        assert!(help.contains("q quit"));
    }
```

Add `use tq_core::{Status, Task};` to the top of the `mod tests` block's imports if not already covered by `use super::*;` — check: `super::*` re-exports whatever `ui.rs` imports, and `ui.rs` doesn't currently import `Status`/`Task` directly (it goes through `app::{..., App, COLUMNS}`). Add this explicit import line inside `mod tests`:

```rust
    use tq_core::{Status, Task};
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cargo test -p tq-tui contextual_help`
Expected: compile error, `cannot find function 'contextual_help' in this scope`.

- [ ] **Step 3: Implement `contextual_help` and use it in `draw_status_bar`**

Replace `draw_status_bar` in `tq-tui/src/ui.rs` with:

```rust
fn contextual_help(app: &App) -> String {
    if app.input.active {
        return "Enter submit  Esc cancel".to_string();
    }

    let mut parts = vec!["j/k row".to_string(), "h/l col".to_string(), "J/K project".to_string()];

    let has_task = !app.tasks_in(app.current_column()).is_empty();
    if has_task {
        parts.push("a add".to_string());
        parts.push("e edit".to_string());
        match app.current_column() {
            Status::Queued => {
                parts.push("s start".to_string());
                parts.push("H hold".to_string());
            }
            Status::Running => {
                parts.push("c complete".to_string());
                parts.push("R requeue".to_string());
            }
            Status::Held => {
                parts.push("r release".to_string());
            }
            Status::Completed => {}
        }
        parts.push("d delete".to_string());
    } else {
        parts.push("a add".to_string());
    }

    parts.push("n new-project".to_string());
    parts.push("?".to_string());
    parts.push("q quit".to_string());

    parts.join("  ")
}

fn draw_status_bar(frame: &mut Frame, app: &App) {
    let help = contextual_help(app);
    let text = if app.status_message.is_empty() {
        help
    } else {
        format!("{}  |  {help}", app.status_message)
    };
    frame.render_widget(Paragraph::new(text).style(Style::default().fg(Color::Gray)), area);
}
```

Note: `draw_status_bar`'s signature already takes `area: Rect` as its third parameter — keep that parameter, only the body changes (the `area` binding used in the last line is the pre-existing function parameter, don't redeclare it). Add `use tq_core::Status;` to the top-level imports in `ui.rs` (not just inside `mod tests`) since `contextual_help` now matches on `Status` directly:

```rust
use tq_core::Status;
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cargo test -p tq-tui contextual_help`
Expected: all 6 tests pass.

- [ ] **Step 5: Run the full tq-tui test suite to check nothing else broke**

Run: `cargo test -p tq-tui`
Expected: all tests pass (Task 1's `modal_height_for` tests plus Task 2's `contextual_help` tests).

- [ ] **Step 6: Commit**

```bash
git add tq-tui/src/ui.rs
git commit -m "tq-tui: replace static help line with contextual per-column status bar"
```

## Task 3: `?` full keybindings overlay

**Files:**
- Modify: `tq-tui/src/app.rs` (add `help_open` field + toggle)
- Modify: `tq-tui/src/main.rs` (route `?`/`Esc`, gate normal-key handling)
- Modify: `tq-tui/src/ui.rs` (new `draw_help_overlay`, call from `draw`)
- Test: `tq-tui/src/app.rs` (new `#[cfg(test)] mod tests`)
- Test: `tq-tui/src/ui.rs` (extend `mod tests`)

- [ ] **Step 1: Write the failing test for the toggle**

Add to the bottom of `tq-tui/src/app.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

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
            should_quit: false,
        }
    }

    #[test]
    fn toggle_help_flips_state() {
        let mut app = minimal_app();
        assert!(!app.help_open);
        app.toggle_help();
        assert!(app.help_open);
        app.toggle_help();
        assert!(!app.help_open);
    }
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cargo test -p tq-tui toggle_help`
Expected: compile error — `App` has no field `help_open` and no method `toggle_help`.

- [ ] **Step 3: Add the field and method to `App`**

In `tq-tui/src/app.rs`, add `pub help_open: bool,` to the `App` struct (after `pending_project_name: String,` on line 46):

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
    pub should_quit: bool,
}
```

Update `App::load` to initialize it (in the struct literal inside `load`, add `help_open: false,` after `pending_project_name: String::new(),`):

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
            should_quit: false,
        };
```

Add the toggle method next to the other `open_*`/`cancel_*` methods (after `cancel_input`):

```rust
    pub fn toggle_help(&mut self) {
        self.help_open = !self.help_open;
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cargo test -p tq-tui toggle_help`
Expected: `toggle_help_flips_state` passes.

- [ ] **Step 5: Route the `?` and `Esc` keys in `main.rs`**

In `tq-tui/src/main.rs`, the `run` function currently branches on `app.input.active`:

```rust
                if app.input.active {
                    handle_input_key(app, key.code);
                } else {
                    handle_normal_key(app, key.code);
                }
```

Change this to also gate on `help_open`, checked before the input branch so `?`/`Esc` always close the overlay first regardless of what else is going on (input can't be active while help is open since both are opened from normal mode, but checking help first is the simpler invariant to reason about):

```rust
                if app.help_open {
                    handle_help_key(app, key.code);
                } else if app.input.active {
                    handle_input_key(app, key.code);
                } else {
                    handle_normal_key(app, key.code);
                }
```

Add the new handler function next to `handle_input_key`:

```rust
fn handle_help_key(app: &mut App, code: KeyCode) {
    match code {
        KeyCode::Char('?') | KeyCode::Esc => app.toggle_help(),
        _ => {}
    }
}
```

Add the `?` binding to `handle_normal_key` (in the `match code` block, anywhere among the other `Char` arms):

```rust
        KeyCode::Char('?') => app.toggle_help(),
```

- [ ] **Step 6: Write the failing test for the overlay's static content**

Add to the `mod tests` block in `tq-tui/src/ui.rs` (from Task 1/2):

```rust
    #[test]
    fn help_overlay_lists_every_key() {
        let text = help_overlay_text();
        for key in [
            "h/l", "j/k", "J/K", "a", "e", "s", "c", "H", "r", "R", "d", "n", "q",
        ] {
            assert!(text.contains(key), "missing key: {key}");
        }
    }
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `cargo test -p tq-tui help_overlay_lists_every_key`
Expected: compile error, `cannot find function 'help_overlay_text' in this scope`.

- [ ] **Step 8: Implement `help_overlay_text` and `draw_help_overlay`, wire into `draw`**

In `tq-tui/src/ui.rs`, add near `draw_input_modal`:

```rust
fn help_overlay_text() -> String {
    [
        "Navigate",
        "  h/l · ←/→   move column",
        "  j/k · ↑/↓   move row",
        "  J/K         switch project",
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

fn draw_help_overlay(frame: &mut Frame) {
    let area = centered_rect(50, 14, frame.area());
    frame.render_widget(Clear, area);
    let block = Block::default()
        .title(" Keybindings ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Cyan));
    let text = Paragraph::new(help_overlay_text()).block(block);
    frame.render_widget(text, area);
}
```

Update `draw` to render the overlay when open, taking priority over the input modal (the two can't both be true given how `help_open`/`input.active` are toggled, but check help first for clarity):

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
    } else if app.input.active {
        draw_input_modal(frame, app);
    }
}
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `cargo test -p tq-tui help_overlay_lists_every_key`
Expected: passes.

- [ ] **Step 10: Add the rendering smoke test deferred from Task 1**

Now that `App` has `help_open`, add this test to `tq-tui/src/ui.rs`'s `mod tests` block (this is the test skipped in Task 1 Step 7):

```rust
    use ratatui::backend::TestBackend;
    use ratatui::Terminal;

    #[test]
    fn draw_does_not_panic_with_long_input_text() {
        let backend = TestBackend::new(80, 24);
        let mut terminal = Terminal::new(backend).unwrap();
        let app = test_app(vec![], 0);
        let mut app = app;
        app.input = InputState {
            active: true,
            prompt: "New task title:".to_string(),
            buffer: "x".repeat(200),
            purpose: InputPurpose::AddTask,
        };
        terminal.draw(|f| draw(f, &app)).unwrap();
    }

    #[test]
    fn draw_does_not_panic_with_help_open() {
        let backend = TestBackend::new(80, 24);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = test_app(vec![], 0);
        app.help_open = true;
        terminal.draw(|f| draw(f, &app)).unwrap();
    }
```

Add `use crate::app::InputPurpose;` to the `mod tests` imports if not already present via `use super::*;` (check `ui.rs`'s top-level imports — it currently imports `App` and `COLUMNS` from `crate::app`, not `InputPurpose`/`InputState`, so add explicitly inside `mod tests`):

```rust
    use crate::app::{InputPurpose, InputState};
```

- [ ] **Step 11: Run the full test suite**

Run: `cargo test -p tq-tui`
Expected: all tests across `app.rs` and `ui.rs` pass (Task 1: 6 tests, Task 2: 6 tests, Task 3: 4 tests = 16 total new tests, plus `toggle_help_flips_state`).

- [ ] **Step 12: Update the README's keybinding list**

In `README.md`, the line documenting TUI keys currently reads:

```
Keys: `a` add task, `e` edit title, `s` start, `c` complete, `H` hold,
`r` release, `R` requeue, `d` delete, `n` register a new project, `q` quit.
```

Change it to:

```
Keys: `a` add task, `e` edit title, `s` start, `c` complete, `H` hold,
`r` release, `R` requeue, `d` delete, `n` register a new project, `?`
show all keybindings, `q` quit. The status bar at the bottom always shows
the keys usable right now for the focused column.
```

- [ ] **Step 13: Run the full workspace test suite and build**

Run: `cargo test --workspace && cargo build --workspace --release`
Expected: everything passes and builds (confirms Tasks 1-3 didn't break `tq-core`/`tq-cli`, which they shouldn't have touched at all).

- [ ] **Step 14: Commit**

```bash
git add tq-tui/src/app.rs tq-tui/src/main.rs tq-tui/src/ui.rs README.md
git commit -m "tq-tui: add ? overlay listing every keybinding"
```

## Self-Review Notes

- **Spec coverage:** Spec item 1 (wrap input modal) → Task 1. Spec item 2 (contextual status bar) → Task 2. Spec item 3 (`?` overlay) → Task 3. Spec's "out of scope" items (no key remapping, no changes to `n`'s flow) are respected — no task touches `submit_input`, `open_new_project`, or any action method.
- **Type consistency:** `Status` variants (`Queued`, `Running`, `Held`, `Completed`) match `tq-core/src/task.rs` exactly. `App` field names (`help_open`, `input`, `tasks`, `column_idx`, `current_column()`, `tasks_in()`) match the existing `tq-tui/src/app.rs` verified during research — no renamed/invented methods.
- **Placeholder scan:** no TBD/TODO. Task 1 Step 7 explicitly walks through why a planned test was cut rather than leaving a vague "add tests" — replaced with a concrete decision (defer to Task 3 Step 10) and that deferred test is fully written out there.
