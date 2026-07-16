use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Clear, List, ListItem, Paragraph};
use ratatui::Frame;

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

fn draw_status_bar(frame: &mut Frame, app: &App, area: Rect) {
    let help = "j/k move  h/l column  J/K lane  a add  e edit  s start  c complete  H hold  r release  R requeue  d delete  n new project  q quit";
    let text = if app.status_message.is_empty() {
        help.to_string()
    } else {
        format!("{}  |  {help}", app.status_message)
    };
    frame.render_widget(Paragraph::new(text).style(Style::default().fg(Color::Gray)), area);
}

fn draw_input_modal(frame: &mut Frame, app: &App) {
    let area = centered_rect(60, 3, frame.area());
    frame.render_widget(Clear, area);
    let block = Block::default()
        .title(app.input.prompt.as_str())
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Cyan));
    let text = Paragraph::new(app.input.buffer.as_str()).block(block);
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
