use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Clear, List, ListItem, Paragraph, Wrap};
use ratatui::Frame;

use tq_core::Status;

use crate::app::{column_label, App, COLUMNS};

fn status_color(idx: usize) -> Color {
    match idx {
        0 => Color::Yellow,   // queued
        1 => Color::Green,    // running
        2 => Color::Magenta,  // held
        _ => Color::DarkGray, // completed
    }
}

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

    if app.input.active {
        draw_input_modal(frame, app);
    }
}

fn draw_lane_bar(frame: &mut Frame, app: &App, area: Rect) {
    let mut spans = Vec::new();
    for (i, lane) in app.lanes.iter().enumerate() {
        let style = if i == app.lane_idx {
            Style::default()
                .fg(Color::Black)
                .bg(Color::Cyan)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::Gray)
        };
        spans.push(Span::styled(format!(" {lane} "), style));
    }
    frame.render_widget(Line::from(spans), area);
}

fn draw_columns(frame: &mut Frame, app: &App, area: Rect) {
    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(25); 4])
        .split(area);

    for (i, status) in COLUMNS.iter().enumerate() {
        let tasks = app.tasks_in(*status);
        let items: Vec<ListItem> = tasks
            .iter()
            .map(|t| ListItem::new(t.title.as_str()))
            .collect();

        let is_focused = i == app.column_idx;
        let border_style = if is_focused {
            Style::default().fg(status_color(i)).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::DarkGray)
        };

        let title = format!(" {} ({}) ", column_label(*status), tasks.len());
        let block = Block::default()
            .title(title)
            .borders(Borders::ALL)
            .border_style(border_style);

        let list = List::new(items).block(block).highlight_style(
            Style::default()
                .bg(status_color(i))
                .fg(Color::Black)
                .add_modifier(Modifier::BOLD),
        );

        let mut state = ratatui::widgets::ListState::default();
        if is_focused && !tasks.is_empty() {
            state.select(Some(app.row_idx[i]));
        }

        frame.render_stateful_widget(list, cols[i], &mut state);
    }
}

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

fn draw_status_bar(frame: &mut Frame, app: &App, area: Rect) {
    let help = contextual_help(app);
    let text = if app.status_message.is_empty() {
        help
    } else {
        format!("{}  |  {help}", app.status_message)
    };
    frame.render_widget(Paragraph::new(text).style(Style::default().fg(Color::Gray)), area);
}

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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::app::InputState;
    use tq_core::{Status, Task};

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
