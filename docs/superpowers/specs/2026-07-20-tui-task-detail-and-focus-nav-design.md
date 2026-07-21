# TUI task detail view + Tab-into-lane-bar focus navigation

Two additions to the `tq-tui` ratatui board, scoped to `tq-tui/src/app.rs`, `tq-tui/src/main.rs`, and `tq-tui/src/ui.rs`.

## 1. Task detail popup

**Problem:** The board only ever shows a task's `title`, truncated to the column width. There's no way to see the full title if it's long, and `Task.notes` (already a field on the model, populated via `push(&title, &notes)`) is never displayed anywhere in the TUI.

**Fix:**
- Add `pub detail_open: bool` to `App` (default `false`, initialized in `App::load`).
- Add `App::open_task_detail(&mut self)`: no-ops if `self.selected_task()` is `None` (empty column), otherwise sets `detail_open = true`.
- Add `App::close_task_detail(&mut self)`: sets `detail_open = false`.
- In `main.rs`'s `run()` loop, `detail_open` joins the existing precedence chain, checked after `help_open` and `input.active` (both already win over normal-mode board interaction) but before falling to `handle_normal_key`:
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
  `handle_detail_key` handles `KeyCode::Enter` and `KeyCode::Esc` (both call `close_task_detail()`), nothing else.
- In `handle_normal_key`, add `KeyCode::Enter => app.open_task_detail()`.
- In `ui.rs::draw`, `detail_open` renders after the board (same layer as the input modal / help overlay) — checked before `input.active`, after `help_open`, matching the precedence order above:
  ```rust
  if app.help_open {
      draw_help_overlay(frame);
  } else if app.detail_open {
      draw_task_detail(frame, app);
  } else if app.input.active {
      draw_input_modal(frame, app);
  }
  ```
- `draw_task_detail` renders a centered modal titled with the column label (e.g. `" QUEUED task "`), containing the full task title (wrapped), then if `notes` is non-empty a blank line followed by `notes: {notes}` (also wrapped), then a blank line and the footer `Enter or Esc to close`. All of this is joined into one string and measured/sized the same way `draw_input_modal` already sizes itself: reuse `modal_height_for(text, width) -> u16` (already generic over any `&str`, not input-specific) to compute height from the full joined string, and the same width-probing (`centered_rect(_, 1, frame.area())`) and `.scroll()`-to-tail approach for overflow. No new sizing logic is written — `draw_task_detail` is a second caller of the existing `modal_height_for` helper.
- No behavior change to `selected_task()`, `tasks_in()`, or any store/action method — this is purely a read-only view layered on existing state.

## 2. Tab-into-lane-bar focus navigation

**Problem:** The only way to switch projects today is `Shift+J`/`Shift+K`, which isn't discoverable and doesn't fit the board's existing `h/l`/`j/k` navigation model. The user wants `Tab` to move focus up to the project-lane bar, where plain `h/l`/arrows switch projects, then back to the board.

**Fix:**
- Add a `Focus` enum to `app.rs`:
  ```rust
  #[derive(Default, Clone, Copy, PartialEq, Eq)]
  pub enum Focus {
      #[default]
      Board,
      LaneBar,
  }
  ```
- Add `pub focus: Focus` to `App` (default `Focus::Board`, initialized in `App::load`).
- Add `App::toggle_focus(&mut self)`: flips between `Board` and `LaneBar`.
- In `main.rs`, `Tab` is handled in `handle_normal_key` (only reachable when `help_open`/`detail_open`/`input.active` are all false, per the existing precedence chain) via `KeyCode::Tab => app.toggle_focus()`.
- `handle_normal_key` branches on `app.focus` for the directional/confirm keys:
  - `Focus::Board` (current behavior, unchanged): `h/l`/arrows → `move_column`, `j/k`/arrows → `move_row`, `Enter` → `open_task_detail` (new, from Part 1).
  - `Focus::LaneBar`: `h/l`/`←/→` → `prev_lane`/`next_lane` (reusing the existing methods verbatim — no new lane-switching logic needed). `j/k`/`↑/↓` → no-op (a single-row bar has no vertical axis). `Enter` and `Esc` → `app.focus = Focus::Board` (both act as "confirm and return to board").
  - `J`/`K` remain bound to `next_lane`/`prev_lane` regardless of `focus` — unchanged from today, so switching projects works both via direct shortcut and via Tab, per explicit user preference for maximum flexibility.
  - All non-directional action keys (`a/e/s/c/H/r/R/d/n/?/q`) remain global regardless of `focus` — no reason to gate them on which bar has focus.
- `ui.rs::draw_lane_bar` gains a visual focus indicator that does NOT change row height (so toggling focus never resizes the columns below it, which would be jarring): keep the lane bar's row in `draw`'s root layout at its current fixed `Constraint::Length(1)`, no border. Instead, when `app.focus == Focus::LaneBar`, swap the styling of the *unselected* lane spans from `Style::default().fg(Color::Gray)` to `Style::default().fg(Color::Cyan)` (brighter, matching the app's existing cyan accent for focused/active UI elements like modal borders), and change the *selected* lane's background from `Color::Cyan` to `Color::Green` so the currently-selected lane still stands out distinctly from the "the whole bar is focus-active" cyan tint. When `Focus::Board` (today's default), render exactly as now: selected lane cyan-on-black bold, unselected lanes plain gray. This is a same-height, color-only change to `draw_lane_bar`'s existing per-lane `Style` selection — no new layout constraints.
- `ui.rs::contextual_help` gains two more early-returns, checked in the same style and order as the existing `app.input.active` check (which stays first since input can happen from either focus state):
  - `app.detail_open` → `"Enter/Esc to close"` (mirrors the existing `input.active` early-return pattern — the detail popup covers the board, so board-oriented hints underneath would be misleading).
  - `app.focus == Focus::LaneBar` → `"h/l · ←/→ switch project  Enter/Esc back to board  q quit"` (kept minimal — no task actions apply while the lane bar has focus).
  - Order: `input.active`, then `detail_open`, then `focus == LaneBar`, then the existing `Board` per-column logic (unchanged) as the fallthrough.

## Out of scope

- No changes to `Task`'s data model — `notes` already exists and is already settable via the existing add-task flow (Part 1 just displays a field that was already there but invisible).
- No changes to the actual set of available actions (`a/e/s/c/H/r/R/d/n`) or their bindings — only `Enter` (new: open detail) and `Tab` (new: toggle focus) are added.
- No removal of `J`/`K` — kept alongside Tab-based lane switching per explicit user direction.
- The `?` help overlay's static text (`help_overlay_text`) should be updated to mention `Tab` (switch to lane bar) and `Enter` (task detail / confirm-and-return, context-dependent) in its "Navigate" section — a documentation update, not a behavior change.
