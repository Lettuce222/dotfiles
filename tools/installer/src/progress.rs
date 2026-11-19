use crate::config::valid_agent;
use crate::{Failure, Result};
use std::env;
use std::io::{self, Read, Write};
use std::process::{Command, Stdio};
use unicode_width::UnicodeWidthChar;

extern "C" {
    fn isatty(fd: i32) -> i32;
}

pub fn terminal(fd: i32) -> bool {
    unsafe { isatty(fd) == 1 }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum State {
    Waiting,
    Running,
    Done,
    Skipped,
    Failed,
}

pub struct Progress {
    steps: Vec<(&'static str, State)>,
    rich: bool,
    color: bool,
    numbered: bool,
    drawn: usize,
    width: usize,
    active: usize,
    tick: usize,
    detail: String,
    measure: Option<(usize, usize)>,
}

impl Progress {
    pub fn new(titles: Vec<&'static str>, plain: bool, numbered: bool) -> Self {
        let (height, width) = if !plain
            && terminal(0)
            && terminal(1)
            && terminal(2)
            && env::var_os("TERM").map_or(false, |value| value != "dumb")
        {
            Command::new("stty")
                .arg("size")
                .stdin(Stdio::inherit())
                .stderr(Stdio::null())
                .output()
                .ok()
                .filter(|out| out.status.success())
                .and_then(|out| {
                    let size = std::str::from_utf8(&out.stdout).ok()?;
                    let mut values = size.split_whitespace();
                    Some((
                        values.next()?.parse::<usize>().ok()?,
                        values.next()?.parse::<usize>().ok()?,
                    ))
                })
                .unwrap_or((0, 0))
        } else {
            (0, 0)
        };
        Self {
            rich: height >= titles.len() + 4 && width >= 58,
            color: env::var_os("NO_COLOR").map_or(true, |value| value.is_empty()),
            numbered,
            steps: titles
                .into_iter()
                .map(|title| (title, State::Waiting))
                .collect(),
            drawn: 0,
            width,
            active: 0,
            tick: 0,
            detail: String::new(),
            measure: None,
        }
    }

    pub fn rich(&self) -> bool {
        self.rich
    }

    pub fn initial(&mut self) {
        self.draw();
    }

    pub fn start(&mut self, index: usize, suffix: Option<&str>) {
        self.active = index;
        self.steps[index].1 = State::Running;
        self.detail = suffix.unwrap_or_default().into();
        self.measure = None;
        self.tick = 0;
        if !self.rich && self.numbered {
            let title = self.steps[index].0;
            let suffix = suffix.map_or_else(String::new, |name| format!(" · {name}"));
            println!(
                "\n[{:02}/{:02}] {title}{suffix}",
                index + 1,
                self.steps.len()
            );
        }
        self.draw();
    }

    pub fn finish(&mut self, result: &Result<Option<String>>) {
        self.steps[self.active].1 = match result {
            Ok(None) => State::Done,
            Ok(Some(_)) => State::Skipped,
            Err(_) => State::Failed,
        };
        self.detail.clear();
        if !self.rich && self.numbered {
            match result {
                Ok(None) => println!("         完了"),
                Ok(Some(reason)) => println!("         スキップ · {reason}"),
                Err(_) => {}
            }
        }
        self.draw();
        if self.rich {
            if let Ok(Some(reason)) = result {
                // Keep a skip explanation in ordinary scrollback below the list.
                self.drawn = 0;
                println!("  – {reason}");
            }
        }
    }

    pub fn update(&mut self, bytes: &[u8]) {
        if !self.rich {
            return;
        }
        let text = String::from_utf8_lossy(bytes);
        if let Some(line) = text
            .rsplit(&['\r', '\n'][..])
            .find(|line| !line.trim().is_empty())
        {
            self.detail = clean(line.trim(), self.width.saturating_sub(5));
            self.measure = self.detail.split_whitespace().find_map(fraction);
        }
    }

    pub fn animate(&mut self) {
        self.tick = self.tick.wrapping_add(1);
        self.draw();
    }

    pub fn pause(&mut self) {
        if self.drawn != 0 {
            // Leave a plain command free to use the original terminal (sudo, prompts).
            print!("\r\x1b[{}F\x1b[J", self.drawn);
            let _ = io::stdout().flush();
            self.drawn = 0;
            println!("  › {}", self.steps[self.active].0);
        }
    }

    fn paint(&self, text: &str, ansi: &str) -> String {
        if self.color {
            format!("\x1b[{ansi}m{text}\x1b[0m")
        } else {
            text.into()
        }
    }

    fn draw(&mut self) {
        if !self.rich {
            return;
        }
        let settled = self
            .steps
            .iter()
            .filter(|(_, state)| matches!(state, State::Done | State::Skipped))
            .count();
        let mut lines = vec![format!(
            "{}  ·  dotfiles  {settled}/{}",
            self.paint("setup", "1;35"),
            self.steps.len()
        )];
        for (title, state) in &self.steps {
            let (mark, ansi) = match state {
                State::Waiting => ("○", "2"),
                State::Running => ("›", "1;35"),
                State::Done => ("✓", "1;32"),
                State::Skipped => ("–", "33"),
                State::Failed => ("✗", "1;31"),
            };
            let row = if *state == State::Running {
                let activity = bar(self.tick, self.measure);
                format!(
                    "  {}  {title}  {}",
                    self.paint(mark, ansi),
                    self.paint(&activity, "35")
                )
            } else {
                format!("  {}  {title}", self.paint(mark, ansi))
            };
            lines.push(row);
        }
        lines.push(
            if self.steps[self.active].1 == State::Running && !self.detail.is_empty() {
                format!("     {}", self.paint(&self.detail, "2"))
            } else {
                String::new()
            },
        );

        let mut output = String::new();
        if self.drawn != 0 {
            output.push_str(&format!("\r\x1b[{}F", self.drawn));
        }
        for line in &lines {
            output.push_str("\r\x1b[2K");
            output.push_str(line);
            output.push('\n');
        }
        let mut stdout = io::stdout().lock();
        let _ = stdout
            .write_all(output.as_bytes())
            .and_then(|()| stdout.flush());
        self.drawn = lines.len();
    }

    pub fn choose_agent(&mut self) -> Result<String> {
        self.pause();
        eprintln!("メインの coding agent CLI を選んでください。");
        let selected = if self.rich {
            match arrow_choice()? {
                Some(index) => index,
                None => number_choice()?,
            }
        } else {
            number_choice()?
        };
        if selected == 0 {
            return Ok("claude".into());
        }
        if selected == 1 {
            return Ok("codex".into());
        }
        loop {
            let choice = prompt("コマンド名（例: aider、空欄で戻る）: ")?;
            if choice.is_empty() {
                return self.choose_agent();
            }
            if valid_agent(&choice) {
                return Ok(choice);
            }
            eprintln!("dotfiles: use a single command name");
        }
    }
}

fn fraction(word: &str) -> Option<(usize, usize)> {
    let (done, total) = word.strip_prefix('[')?.strip_suffix(']')?.split_once('/')?;
    let (done, total) = (done.parse::<usize>().ok()?, total.parse::<usize>().ok()?);
    (total > 0 && done <= total).then_some((done, total))
}

fn bar(tick: usize, measure: Option<(usize, usize)>) -> String {
    if let Some((done, total)) = measure {
        let fill = done.saturating_mul(12) / total;
        return format!("{}{}", "━".repeat(fill), "─".repeat(12 - fill));
    }
    let position = tick % 16;
    let left = position.min(16 - position);
    format!("{}━━━━{}", "─".repeat(left), "─".repeat(8 - left))
}

pub fn clean(line: &str, limit: usize) -> String {
    let mut chars = line.chars().peekable();
    let mut result = String::new();
    let mut columns = 0;
    while let Some(ch) = chars.next() {
        if ch == '\x1b' && chars.peek() == Some(&'[') {
            chars.next();
            for byte in chars.by_ref() {
                if ('@'..='~').contains(&byte) {
                    break;
                }
            }
        } else if !ch.is_control() {
            columns += ch.width().unwrap_or(0);
            if columns > limit {
                result.push('…');
                break;
            }
            result.push(ch);
        }
    }
    result
}

const CHOICES: [&str; 3] = [
    "Claude Code (default)",
    "Codex",
    "その他（コマンド名を入力）",
];

fn cancelled() -> Failure {
    Failure::new(1, "CLI の選択を中止しました。")
}

fn prompt(label: &str) -> Result<String> {
    eprint!("{label}");
    io::stderr().flush()?;
    let mut line = String::new();
    if io::stdin().read_line(&mut line)? == 0 {
        return Err(cancelled());
    }
    Ok(line.trim_end_matches(['\r', '\n']).into())
}

fn number_choice() -> Result<usize> {
    for (index, label) in CHOICES.iter().enumerate() {
        eprintln!("  {}  {label}", index + 1);
    }
    loop {
        match prompt("選択 [1]: ")?.as_str() {
            "" | "1" => return Ok(0),
            "2" => return Ok(1),
            "3" => return Ok(2),
            _ => eprintln!("1、2、3 のいずれかを選んでください。"),
        }
    }
}

struct InputMode(String);

impl Drop for InputMode {
    fn drop(&mut self) {
        let _ = Command::new("stty").arg(&self.0).status();
    }
}

fn arrow_choice() -> Result<Option<usize>> {
    let saved = Command::new("stty")
        .arg("-g")
        .stdin(Stdio::inherit())
        .stderr(Stdio::null())
        .output();
    let saved = match saved {
        Ok(output) if output.status.success() => {
            String::from_utf8_lossy(&output.stdout).trim().to_owned()
        }
        _ => return Ok(None),
    };
    let _restore = InputMode(saved);
    if !Command::new("stty")
        .args(["-icanon", "-echo", "-isig", "min", "1", "time", "0"])
        .status()?
        .success()
    {
        return Ok(None);
    }
    let mut input = io::stdin().lock();
    let mut stderr = io::stderr().lock();
    let mut index = 0;
    let mut rendered = false;
    loop {
        if rendered {
            write!(stderr, "\r\x1b[4F")?;
        }
        for (i, label) in CHOICES.iter().enumerate() {
            writeln!(
                stderr,
                "\x1b[2K  {} {label}",
                if i == index { "❯" } else { " " }
            )?;
        }
        writeln!(stderr, "\x1b[2K  ↑↓ 選択 · Enter 確定")?;
        stderr.flush()?;
        rendered = true;
        let mut key = [0];
        if input.read_exact(&mut key).is_err() {
            return Err(cancelled());
        }
        match key[0] {
            b'\r' | b'\n' => return Ok(Some(index)),
            b'1'..=b'3' => index = usize::from(key[0] - b'1'),
            3 | 4 | b'q' => return Err(cancelled()),
            27 => {
                let mut suffix = [0; 2];
                if input.read_exact(&mut suffix).is_err() {
                    return Err(cancelled());
                }
                match &suffix {
                    b"[A" => index = (index + 2) % 3,
                    b"[B" => index = (index + 1) % 3,
                    _ => {}
                }
            }
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{bar, clean, fraction};

    #[test]
    fn package_progress_uses_real_counts_when_available() {
        assert_eq!(fraction("[2/3]"), Some((2, 3)));
        assert_eq!(fraction("[4/3]"), None);
        assert_eq!(fraction("[0/0]"), None);
        assert_eq!(bar(0, Some((2, 3))), "━━━━━━━━────");
        assert_ne!(bar(0, None), bar(1, None));
    }

    #[test]
    fn live_output_strips_ansi_and_fits_terminal_columns() {
        assert_eq!(clean("\x1b[31mエラー\x1b[0m", 4), "エラ…");
    }
}
