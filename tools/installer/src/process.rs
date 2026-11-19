use crate::config::private_dir;
use crate::progress::{clean, Progress};
use crate::{Failure, Result};
use std::env;
use std::ffi::OsStr;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::os::unix::process::ExitStatusExt;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::sync::mpsc::{self, SyncSender};
use std::thread;
use std::time::{Duration, Instant};

const TICK: Duration = Duration::from_millis(90);

pub fn find(program: impl AsRef<OsStr>) -> Option<PathBuf> {
    let program = Path::new(program.as_ref());
    let is_executable = |path: &Path| {
        fs::metadata(path).map_or(false, |info| {
            info.is_file() && info.permissions().mode() & 0o111 != 0
        })
    };
    if program.components().count() > 1 {
        return is_executable(program).then(|| program.into());
    }
    env::var_os("PATH").and_then(|path| {
        env::split_paths(&path)
            .map(|dir| dir.join(program))
            .find(|path| is_executable(path))
    })
}

pub fn code(status: ExitStatus) -> i32 {
    status
        .code()
        .unwrap_or_else(|| 128 + status.signal().unwrap_or(1))
}

fn check(status: ExitStatus, program: &OsStr) -> Result<()> {
    if status.success() {
        Ok(())
    } else {
        Err(Failure::new(
            code(status),
            format!("{} が正常終了しませんでした。", program.to_string_lossy()),
        ))
    }
}

struct Packet(bool, Vec<u8>);

fn relay(mut source: impl Read, stderr: bool, sender: SyncSender<Packet>) -> io::Result<()> {
    let mut buffer = [0; 4096];
    loop {
        let count = source.read(&mut buffer)?;
        if count == 0
            || sender
                .send(Packet(stderr, buffer[..count].to_vec()))
                .is_err()
        {
            return Ok(());
        }
    }
}

pub struct RunLog {
    path: PathBuf,
    file: File,
}

impl RunLog {
    pub fn new() -> Result<Self> {
        let directory = private_dir(&env::temp_dir(), "dotfiles-setup-")?;
        let path = directory.join("setup.log");
        let file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&path)?;
        Ok(Self { path, file })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn record(&mut self, line: &str) -> Result<()> {
        writeln!(&mut self.file, "{line}")?;
        self.file.flush()?;
        Ok(())
    }

    pub fn discard(self) {
        let Self { path, file } = self;
        drop(file);
        let _ = fs::remove_file(&path);
        if let Some(parent) = path.parent() {
            let _ = fs::remove_dir(parent);
        }
    }

    pub fn log_tail(&self) -> String {
        use std::io::{Seek, SeekFrom};
        let mut bytes = Vec::new();
        if let Ok(mut file) = File::open(&self.path) {
            if let Ok(meta) = file.metadata() {
                let _ = file.seek(SeekFrom::Start(meta.len().saturating_sub(16_384)));
            }
            let _ = file.take(16_384).read_to_end(&mut bytes);
        }
        let text = String::from_utf8_lossy(&bytes);
        let lines: Vec<_> = text
            .lines()
            .rev()
            .take(12)
            .map(|line| clean(line, 200))
            .collect();
        lines.into_iter().rev().collect::<Vec<_>>().join("\n")
    }

    pub fn capture(&mut self, progress: &mut Progress, command: &mut Command) -> Result<()> {
        let program = command.get_program().to_os_string();
        self.record(&format!("$ {}", program.to_string_lossy()))?;
        let mut child = command
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| Failure::new(1, format!("{}: {error}", program.to_string_lossy())))?;
        let (sender, channel) = mpsc::sync_channel(32);
        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();
        let out = sender.clone();
        let out = thread::spawn(move || relay(stdout, false, out));
        let err = thread::spawn(move || relay(stderr, true, sender));
        let mut last_tick = Instant::now();
        let streamed = (|| -> io::Result<()> {
            loop {
                match channel.recv_timeout(TICK) {
                    Ok(Packet(stderr, bytes)) => {
                        self.file.write_all(&bytes)?;
                        if progress.rich() {
                            progress.update(&bytes);
                        } else if stderr {
                            io::stderr().write_all(&bytes)?;
                            io::stderr().flush()?;
                        } else {
                            io::stdout().write_all(&bytes)?;
                            io::stdout().flush()?;
                        }
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => {}
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
                if last_tick.elapsed() >= TICK {
                    progress.animate();
                    last_tick = Instant::now();
                }
            }
            Ok(())
        })();
        drop(channel);
        if streamed.is_err() {
            let _ = child.kill();
        }
        let status = child.wait()?;
        for reader in [out, err] {
            if let Ok(result) = reader.join() {
                result?;
            }
        }
        streamed?;
        self.file.flush()?;
        check(status, &program)
    }

    pub fn live(
        &mut self,
        progress: &mut Progress,
        command: &mut Command,
        input: Option<&[u8]>,
    ) -> Result<()> {
        progress.pause();
        let program = command.get_program().to_os_string();
        self.record(&format!("$ {} (live terminal)", program.to_string_lossy()))?;
        let command = command.stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::inherit()
        });
        let mut child = command
            .spawn()
            .map_err(|error| Failure::new(1, format!("{}: {error}", program.to_string_lossy())))?;
        let written = if let Some(input) = input {
            child.stdin.take().unwrap().write_all(input)
        } else {
            Ok(())
        };
        let status = child.wait()?;
        check(status, &program)?;
        written?;
        Ok(())
    }

    pub fn bootstrap(&mut self, progress: &mut Progress, url: &str, shell: &str) -> Result<()> {
        let response = Command::new("curl").args(["-fsSL", url]).output()?;
        if !response.stderr.is_empty() {
            self.file.write_all(&response.stderr)?;
            if !response.status.success() {
                io::stderr().write_all(&response.stderr)?;
            }
        }
        check(response.status, OsStr::new("curl"))?;
        let script = String::from_utf8(response.stdout)
            .map_err(|error| Failure::new(1, error.to_string()))?;
        self.live(progress, Command::new(shell).arg("-c").arg(script), None)
    }
}
