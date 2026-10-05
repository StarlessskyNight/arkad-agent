//! arkad-frame: the cybernode cyber-frame as a standalone Rust TUI.
//! Live stats header, interactive directory tree, routed prompt.
//! Stand-in for the Python cyber frame; keeps tree + header + routing lean.

use crossterm::{
    event::{self, Event, KeyCode, KeyEventKind},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Wrap},
    Frame, Terminal,
};
use std::fs;
use std::io;
use std::time::{Duration, Instant};

fn main() -> io::Result<()> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let mut term = Terminal::new(CrosstermBackend::new(stdout))?;
    let res = run(&mut term);
    disable_raw_mode()?;
    execute!(term.backend_mut(), LeaveAlternateScreen)?;
    res
}

struct App {
    entries: Vec<Entry>,
    list_state: ListState,
    input: String,
    log: Vec<String>,
    stats: Stats,
    last: Instant,
    uptime0: Instant,
}

struct Entry {
    name: String,
    is_dir: bool,
}

#[derive(Default)]
struct Stats {
    ram_used: f64,
    ram_total: f64,
    cpu: f64,
}

fn load_stats() -> Stats {
    let mut used = 0.0;
    let mut total = 0.0;
    if let Ok(s) = fs::read_to_string("/proc/meminfo") {
        for line in s.lines() {
            if let Some(v) = line.strip_prefix("MemTotal:") {
                total = v.trim().split_whitespace().next().and_then(|x| x.parse().ok()).unwrap_or(0.0) / 1048576.0;
            } else if let Some(v) = line.strip_prefix("MemAvailable:") {
                used = total - v.trim().split_whitespace().next().and_then(|x| x.parse().ok()).unwrap_or(0.0) / 1048576.0;
            }
        }
    }
    Stats { ram_used: used, ram_total: total, cpu: 0.0 }
}

fn dir_entries() -> Vec<Entry> {
    let mut out: Vec<Entry> = fs::read_dir(".")
        .map(|d| {
            d.filter_map(|e| e.ok())
                .filter(|e| !e.file_name().to_string_lossy().starts_with('.'))
                .map(|e| Entry {
                    name: e.file_name().to_string_lossy().into_owned(),
                    is_dir: e.file_type().map(|t| t.is_dir()).unwrap_or(false),
                })
                .collect()
        })
        .unwrap_or_default();
    out.sort_by(|a, b| (!a.is_dir).cmp(&!b.is_dir).then(a.name.to_lowercase().cmp(&b.name.to_lowercase())));
    out
}

fn route(text: &str) -> &'static str {
    if text.starts_with('/') {
        "[command]"
    } else if text.starts_with('!') {
        "[shell]"
    } else if text.contains('\n') || text.len() > 400 {
        "[examine pasted content]"
    } else {
        "[llm]"
    }
}

fn run(term: &mut Terminal<CrosstermBackend<io::Stdout>>) -> io::Result<()> {
    let mut app = App {
        entries: dir_entries(),
        list_state: ListState::default().with_selected(Some(0)),
        input: String::new(),
        log: Vec::new(),
        stats: load_stats(),
        last: Instant::now(),
        uptime0: Instant::now(),
    };
    let mut prev_cpu: Option<(u64, u64)> = None;
    loop {
        if app.last.elapsed() >= Duration::from_secs(1) {
            app.stats = load_stats();
            if let Ok(s) = fs::read_to_string("/proc/stat") {
                if let Some(line) = s.lines().next() {
                    let nums: Vec<u64> = line.split_whitespace().skip(1).filter_map(|x| x.parse().ok()).collect();
                    if nums.len() >= 4 {
                        let idle = nums[3] + nums.get(4).copied().unwrap_or(0);
                        let total: u64 = nums.iter().sum();
                        if let Some((pi, pt)) = prev_cpu {
                            let dt = total.saturating_sub(pt);
                            let di = idle.saturating_sub(pi);
                            if dt > 0 {
                                app.stats.cpu = ((1.0 - di as f64 / dt as f64) * 100.0).clamp(0.0, 100.0);
                            }
                        }
                        prev_cpu = Some((idle, total));
                    }
                }
            }
            app.last = Instant::now();
        }

        term.draw(|f| ui(f, &mut app))?;

        if event::poll(Duration::from_millis(100))? {
            if let Event::Key(key) = event::read()? {
                if key.kind != KeyEventKind::Press {
                    continue;
                }
                match key.code {
                    KeyCode::Esc => return Ok(()),
                    KeyCode::Up => {
                        let i = app.list_state.selected().unwrap_or(0);
                        app.list_state.select(Some(i.saturating_sub(1)));
                    }
                    KeyCode::Down => {
                        let i = app.list_state.selected().unwrap_or(0);
                        app.list_state.select(Some((i + 1).min(app.entries.len() - 1)));
                    }
                    KeyCode::Char(c) => app.input.push(c),
                    KeyCode::Backspace => { app.input.pop(); }
                    KeyCode::Enter => {
                        if app.input.trim().is_empty() {
                            continue;
                        }
                        let r = route(&app.input);
                        app.log.push(format!("> {}  -> {}", app.input, r));
                        app.input.clear();
                    }
                    _ => {}
                }
            }
        }
    }
}

fn ui(f: &mut Frame, app: &mut App) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(1), Constraint::Length(1), Constraint::Min(3), Constraint::Length(3)])
        .split(f.area());

    // top stats header
    let ram_fill = ((app.stats.ram_used / app.stats.ram_total.max(1.0)) * 8.0) as usize;
    let cpu_fill = ((app.stats.cpu / 25.0) as usize).min(4);
    let up = app.uptime0.elapsed().as_secs();
    let header = Line::from(vec![
        Span::styled(format!("{} RAM {:.0}G/{:.0}G  ", "▒".repeat(ram_fill.min(8)), app.stats.ram_used, app.stats.ram_total), Style::default().fg(Color::Magenta)),
        Span::raw("|  "),
        Span::styled(format!("{} CPU {:.0}%  ", "▇".repeat(cpu_fill), app.stats.cpu), Style::default().fg(Color::Magenta)),
        Span::raw("|  "),
        Span::styled(format!("UPTIME {}:{:02}:{:02}", up / 3600, (up % 3600) / 60, up % 60), Style::default().fg(Color::Cyan)),
    ]);
    f.render_widget(Paragraph::new(header), chunks[0]);

    let rule = Line::from("─".repeat(chunks[1].width as usize));
    f.render_widget(Paragraph::new(rule).style(Style::default().fg(Color::DarkGray)), chunks[1]);

    let mid = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(38), Constraint::Percentage(62)])
        .split(chunks[2]);

    let items: Vec<ListItem> = app
        .entries
        .iter()
        .map(|e| {
            if e.is_dir {
                ListItem::new(format!("󰉋 {}/", e.name))
            } else {
                ListItem::new(format!("  {}", e.name))
            }
        })
        .collect();
    let tree = List::new(items)
        .block(Block::default().borders(Borders::ALL).title("ROOT_DIR"))
        .highlight_style(Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD));
    f.render_stateful_widget(tree, mid[0], &mut app.list_state);

    let info = format!(
        "v0.1.0\n{}\n\n{}\n\n{}\n\n type /cmd, !cmd, paste-long, or free text",
        std::env::current_dir().map(|p| p.display().to_string()).unwrap_or_default(),
        app.log.iter().rev().take(6).rev().cloned().collect::<Vec<_>>().join("\n"),
        "Esc quits"
    );
    f.render_widget(
        Paragraph::new(info)
            .block(Block::default().borders(Borders::ALL).title("RENDER_VIEW"))
            .wrap(Wrap { trim: false }),
        mid[1],
    );

    let prompt = Paragraph::new(format!("❯ {}", app.input)).block(
        Block::default().borders(Borders::ALL).title("prompt"),
    );
    f.render_widget(prompt, chunks[3]);
}
