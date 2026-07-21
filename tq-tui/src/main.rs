mod app;
mod ui;

use std::io;
use std::time::Duration;

use crossterm::event::{self, Event, KeyCode, KeyEventKind};
use crossterm::execute;
use crossterm::terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;

use app::{App, Focus};

fn main() -> io::Result<()> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let mut app = App::load().expect("failed to load tq state");
    let result = run(&mut terminal, &mut app);

    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    result
}

fn run<B: ratatui::backend::Backend>(terminal: &mut Terminal<B>, app: &mut App) -> io::Result<()> {
    loop {
        terminal.draw(|f| ui::draw(f, app))?;

        if event::poll(Duration::from_millis(500))? {
            if let Event::Key(key) = event::read()? {
                if key.kind != KeyEventKind::Press {
                    continue;
                }
                if app.help_open {
                    handle_help_key(app, key.code);
                } else if app.detail.is_some() {
                    handle_detail_key(app, key.code);
                } else if app.input.active {
                    handle_input_key(app, key.code);
                } else {
                    handle_normal_key(app, key.code);
                }
            }
        } else {
            let _ = app.refresh();
        }

        if app.should_quit {
            return Ok(());
        }
    }
}

fn handle_input_key(app: &mut App, code: KeyCode) {
    match code {
        KeyCode::Enter => app.submit_input(),
        KeyCode::Esc => app.cancel_input(),
        KeyCode::Backspace => app.input_backspace(),
        KeyCode::Char(c) => app.input_char(c),
        _ => {}
    }
}

fn handle_help_key(app: &mut App, code: KeyCode) {
    match code {
        KeyCode::Char('?') | KeyCode::Esc => app.toggle_help(),
        _ => {}
    }
}

fn handle_detail_key(app: &mut App, code: KeyCode) {
    match code {
        KeyCode::Enter | KeyCode::Esc => app.close_task_detail(),
        _ => {}
    }
}

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
