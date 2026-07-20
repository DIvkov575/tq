# TUI navigation/bindings polish

Three fixes to the `tq-tui` ratatui board, scoped to `tq-tui/src/app.rs` and `tq-tui/src/ui.rs`.

## 1. Wrap text in the input modal

**Problem:** `draw_input_modal` renders the buffer as a single-line `Paragraph` inside a fixed 3-row-tall box (`centered_rect(60, 3, ...)`). A long task title while typing overflows past the box border instead of wrapping.

**Fix:**
- Add `.wrap(Wrap { trim: false })` to the `Paragraph` in `draw_input_modal`.
- Compute the wrapped line count from `app.input.buffer` and the modal's inner width, and size the modal height to fit (minimum 1 line, same as today for short input), capped at a max height (8 lines) so a very long paste can't fill the screen. Use a scroll offset (`Paragraph::scroll`) if the buffer's wrapped height ever exceeds the cap, keeping the cursor's line in view.
- `centered_rect` takes height as a parameter already; pass the computed height instead of the hardcoded `3`.

## 2. Contextual single-line status bar

**Problem:** `draw_status_bar` always renders the same 96-character help string with every key, regardless of what's usable right now. It's cramped and includes actions that don't apply to the current column (e.g. `s start` shown while looking at COMPLETED).

**Fix:** Replace the static `help` string in `draw_status_bar` with a function `contextual_help(app: &App) -> String` that builds the line from current state:

- **Input active:** `Enter submit  Esc cancel` (nothing else).
- **Help overlay open:** status bar content doesn't matter (overlay covers it) — no special case needed beyond leaving current logic as-is underneath.
- **Normal mode**, built from three fixed segments plus one variable segment:
  - Always: `j/k row  h/l col  J/K project`
  - Variable, keyed off `app.current_column()`:
    - `Queued` → `a add  e edit  s start  H hold  d delete`
    - `Running` → `a add  e edit  c complete  R requeue  d delete`
    - `Held` → `a add  e edit  r release  d delete`
    - `Completed` → `a add  e edit  d delete`
  - If the current column has zero tasks (`app.tasks_in(current_column()).is_empty()`), drop the task-only keys from the variable segment (`e/s/c/H/r/R/d`) since there's no selected task — keep `a add`.
  - Always appended: `n new-project  ?  q quit`
- `app.status_message`, when non-empty, still prepends exactly as today: `"{status_message}  |  {help}"`.

This is purely a `ui.rs` rendering change — no new `App` state needed beyond what already exists (`current_column()`, `tasks_in()`).

## 3. `?` full keybindings overlay

**Problem:** No single place lists every key at once; the contextual bar (by design) only shows what's currently relevant.

**Fix:**
- Add `pub help_open: bool` to `App` (default `false`).
- In `main.rs::handle_normal_key`, add `KeyCode::Char('?') => app.help_open = !app.help_open`. When `help_open` is true, other normal-mode keys are ignored except `?` and `Esc` (both close it) — mirrors how `app.input.active` already gates key handling, so add the check next to that existing branch in `run()`.
- In `ui.rs::draw`, if `app.help_open`, render a centered modal (reuse `centered_rect`, larger fixed size e.g. 50w x 14h) listing every key grouped under headers: `Navigate`, `Task actions`, `Project`, `Quit` — same groups as the README's keybinding list. Static content, not built from state.
- Footer line inside the modal: `? or Esc to close`.

## Out of scope

- No changes to the actual key-to-action mapping or column/lane navigation behavior (confirmed: current bindings are fine, only their presentation needed work).
- No changes to `n` / add-project flow — it already round-trips name → directory → `ProjectStore::add`; it was simply undiscovered. Its keys now surface in the always-visible segment of the contextual bar instead of being buried in a 96-char static line.
