use crate::{Failure, Result};
use serde_json::Value;
use std::env;
use std::ffi::OsStr;
use std::fs::{self, DirBuilder, OpenOptions};
use std::io::{ErrorKind, Write};
use std::os::unix::fs::{symlink, DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

const IGNORE_BEGIN: &str =
    "# >>> dotfiles: configs/git/ignore.shared から install.sh が書く。ここから下の区切りまでは直さない";
const IGNORE_END: &str = "# <<< dotfiles";
static TEMP_ID: AtomicUsize = AtomicUsize::new(0);

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Missing,
    Link,
    File,
    Directory,
    Other,
}

fn kind(path: &Path) -> Result<Kind> {
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.is_symlink() => Ok(Kind::Link),
        Ok(meta) if meta.is_file() => Ok(Kind::File),
        Ok(meta) if meta.is_dir() => Ok(Kind::Directory),
        Ok(_) => Ok(Kind::Other),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(Kind::Missing),
        Err(error) => Err(at(path, error)),
    }
}

fn at(path: &Path, error: impl std::fmt::Display) -> Failure {
    Failure::new(1, format!("{}: {error}", path.display()))
}

pub fn private_dir(parent: &Path, prefix: &str) -> Result<PathBuf> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    for _ in 0..16 {
        let path = parent.join(format!(
            "{prefix}{}-{}-{}",
            std::process::id(),
            now.as_nanos(),
            TEMP_ID.fetch_add(1, Ordering::Relaxed)
        ));
        match DirBuilder::new().mode(0o700).create(&path) {
            Ok(()) => return Ok(path),
            Err(error) if error.kind() == ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(at(&path, error)),
        }
    }
    Err(at(parent, "could not allocate a private directory"))
}

fn write_atomic(path: &Path, bytes: &[u8], mode: u32) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| at(path, "missing parent directory"))?;
    let temporary = private_dir(parent, ".dotfiles-write-")?;
    let file = temporary.join("data");
    let result = (|| {
        let mut writer = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(mode)
            .open(&file)?;
        writer.write_all(bytes)?;
        fs::rename(&file, path)
    })();
    let _ = fs::remove_file(&file);
    let _ = fs::remove_dir(&temporary);
    result.map_err(|error| at(path, error))
}

fn entries(path: &Path) -> Result<Vec<PathBuf>> {
    if !path.is_dir() {
        return Ok(Vec::new());
    }
    let mut paths = fs::read_dir(path)
        .map_err(|error| at(path, error))?
        .map(|entry| {
            entry
                .map(|value| value.path())
                .map_err(|error| at(path, error))
        })
        .collect::<Result<Vec<_>>>()?;
    paths.sort();
    Ok(paths)
}

pub fn valid_agent(name: &str) -> bool {
    name.as_bytes()
        .first()
        .map_or(false, u8::is_ascii_alphanumeric)
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._+-".contains(&byte))
}

fn validate_agent(name: &str) -> Result<()> {
    if valid_agent(name) {
        Ok(())
    } else {
        Err(Failure::new(
            2,
            format!("dotfiles: use a single command name (got {name:?})"),
        ))
    }
}

pub struct Config {
    pub root: PathBuf,
    pub home: PathBuf,
    pub dry_run: bool,
    pub links_only: bool,
    changes: Vec<String>,
    skips: Vec<String>,
}

impl Config {
    pub fn new(root: PathBuf, home: PathBuf, dry_run: bool, links_only: bool) -> Self {
        Self {
            root,
            home,
            dry_run,
            links_only,
            changes: Vec::new(),
            skips: Vec::new(),
        }
    }

    fn change(&mut self, change: String) {
        self.changes.push(change);
    }

    fn skip(&mut self, skip: String) {
        self.skips.push(format!("skip: {skip}"));
    }

    pub fn report(&self) {
        if self.links_only {
            let prefix = if self.dry_run { "(dry-run) " } else { "" };
            if self.changes.is_empty() {
                println!("{prefix}変更なし");
            } else {
                for change in &self.changes {
                    println!("{prefix}{change}");
                }
            }
            for skip in &self.skips {
                println!("{skip}");
            }
        } else {
            for skip in &self.skips {
                eprintln!("{skip}");
            }
        }
    }

    fn directory(&mut self, path: &Path) -> Result<()> {
        if path.is_dir() {
            return Ok(());
        }
        if kind(path)? != Kind::Missing {
            return Err(at(path, "exists and is not a directory; left it in place"));
        }
        self.change(format!("mkdir {}", path.display()));
        if !self.dry_run {
            fs::create_dir_all(path).map_err(|error| at(path, error))?;
        }
        Ok(())
    }

    // Replace only symlinks. Codex's provider-local links can also belong to the user.
    fn link(&mut self, source: &Path, destination: &Path, replace: bool) -> Result<()> {
        match kind(destination)? {
            Kind::Link => {
                let previous = fs::read_link(destination)?;
                if previous == source {
                    return Ok(());
                }
                if !replace {
                    self.skip(format!(
                        "{} already exists; left it in place",
                        destination.display()
                    ));
                    return Ok(());
                }
                self.change(format!(
                    "relink {} -> {} (was {})",
                    destination.display(),
                    source.display(),
                    previous.display()
                ));
                if !self.dry_run {
                    let parent = destination.parent().unwrap();
                    let temporary = private_dir(parent, ".dotfiles-link-")?;
                    let link = temporary.join("link");
                    let result =
                        symlink(source, &link).and_then(|()| fs::rename(&link, destination));
                    let _ = fs::remove_file(&link);
                    let _ = fs::remove_dir(&temporary);
                    result.map_err(|error| at(destination, error))?;
                }
            }
            Kind::Missing => {
                self.change(format!(
                    "link {} -> {}",
                    destination.display(),
                    source.display()
                ));
                if !self.dry_run {
                    symlink(source, destination).map_err(|error| at(destination, error))?;
                }
            }
            _ => {
                let reason = if replace {
                    "is not a symlink"
                } else {
                    "already exists"
                };
                self.skip(format!(
                    "{} {reason}; left it in place",
                    destination.display()
                ));
            }
        }
        Ok(())
    }

    pub fn select_agent(
        &mut self,
        interactive: bool,
        prompt: impl FnOnce() -> Result<String>,
    ) -> Result<String> {
        let source = self.root.join("configs/agent/cli.local");
        let destination = self.home.join(".config/dotfiles-agent-cli");
        let source_kind = kind(&source)?;
        let dest_kind = kind(&destination)?;
        if !matches!(source_kind, Kind::Missing | Kind::File) {
            return Err(at(&source, "expected a regular file"));
        }
        if !matches!(dest_kind, Kind::Missing | Kind::File | Kind::Link) {
            return Err(at(&destination, "expected a file or symlink"));
        }
        if dest_kind == Kind::Link && fs::read_link(&destination)? != source {
            return Err(at(
                &destination,
                "points outside this checkout; move it aside first",
            ));
        }
        let saved = if source_kind == Kind::File {
            fs::read_to_string(&source)?
        } else if dest_kind == Kind::File {
            fs::read_to_string(&destination)?
        } else {
            String::new()
        };
        let saved = saved.trim_end_matches('\n');
        let override_name = env::var("DOTFILES_AGENT").unwrap_or_default();
        let selected =
            if saved.is_empty() && override_name.is_empty() && interactive && !self.dry_run {
                prompt()?
            } else if saved.is_empty() {
                "claude".into()
            } else {
                saved.into()
            };
        validate_agent(&selected)?;
        let active = if override_name.is_empty() {
            selected.clone()
        } else {
            override_name
        };
        validate_agent(&active)?;

        self.directory(&self.home.join(".config"))?;
        if dest_kind == Kind::File {
            if source_kind == Kind::File {
                self.change(format!(
                    "back up {} before linking it to {}",
                    destination.display(),
                    source.display()
                ));
                if !self.dry_run {
                    let backup =
                        private_dir(destination.parent().unwrap(), "dotfiles-agent-cli.bak.")?;
                    fs::rename(&destination, backup.join("choice"))?;
                    self.change(format!(
                        "backed up {} to {}/choice",
                        destination.display(),
                        backup.display()
                    ));
                }
            } else {
                self.change(format!(
                    "move {} to {}",
                    destination.display(),
                    source.display()
                ));
                if !self.dry_run {
                    // A non-clobbering copy also supports checkouts on a separate mount.
                    let original = fs::read(&destination)?;
                    let mut target = OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .mode(0o600)
                        .open(&source)?;
                    target.write_all(&original)?;
                    fs::remove_file(&destination)?;
                }
            }
        }
        if saved.is_empty() {
            self.change(format!("write {} ({selected})", source.display()));
            if !self.dry_run {
                write_atomic(&source, format!("{selected}\n").as_bytes(), 0o600)?;
            }
        }
        if self.dry_run && dest_kind == Kind::File {
            self.change(format!(
                "link {} -> {}",
                destination.display(),
                source.display()
            ));
        } else {
            self.link(&source, &destination, false)?;
        }
        Ok(active)
    }

    pub fn apply(&mut self, agent: &str) -> Result<()> {
        let configs = self.root.join("configs");
        for source in entries(&configs)?.into_iter().filter(|path| path.is_dir()) {
            let name = source.file_name().unwrap();
            if !["claude", "agent", "hammerspoon"]
                .iter()
                .any(|n| name == OsStr::new(n))
            {
                self.link(&source, &self.home.join(".config").join(name), true)?;
            }
        }
        self.git_ignore()?;
        let shared = configs.join("agent");
        self.link(&shared, &self.home.join(".config/dotfiles-agent"), true)?;
        match agent {
            "claude" => self.claude(&configs, &shared)?,
            "codex" => self.codex(&shared)?,
            _ => {}
        }
        let hammerspoon = configs.join("hammerspoon");
        if hammerspoon.is_dir() {
            self.link(&hammerspoon, &self.home.join(".hammerspoon"), true)?;
        }
        Ok(())
    }

    fn git_ignore(&mut self) -> Result<()> {
        let shared = self.root.join("configs/git/ignore.shared");
        if !shared.is_file() {
            return Ok(());
        }
        let destination = shared.with_file_name("ignore");
        let exists = kind(&destination)?;
        if !matches!(exists, Kind::Missing | Kind::File) {
            self.skip(format!(
                "{} is not a regular file; left it in place",
                destination.display()
            ));
            return Ok(());
        }
        let old = if exists == Kind::File {
            fs::read_to_string(&destination)?
        } else {
            String::new()
        };
        let shared_lines = fs::read_to_string(&shared)?;
        let mut updated = format!("{IGNORE_BEGIN}\n");
        for line in shared_lines.lines() {
            updated.push_str(line);
            updated.push('\n');
        }
        updated.push_str(IGNORE_END);
        updated.push('\n');
        let mut inside = false;
        for line in old.lines() {
            match line {
                IGNORE_BEGIN => inside = true,
                IGNORE_END if inside => inside = false,
                _ if !inside => {
                    updated.push_str(line);
                    updated.push('\n');
                }
                _ => {}
            }
        }
        if old != updated {
            let action = if exists == Kind::File {
                "update"
            } else {
                "write"
            };
            self.change(format!(
                "{action} {} from {}",
                destination.display(),
                shared.display()
            ));
            if !self.dry_run {
                write_atomic(&destination, updated.as_bytes(), 0o644)?;
                if !self.links_only {
                    println!("Generated {}", destination.display());
                }
            }
        }
        Ok(())
    }

    fn skills(&mut self, shared: &Path, home: &Path, claude: bool) -> Result<()> {
        let source = shared.join("skills");
        let destination = home.join("skills");
        if !source.is_dir() {
            return Ok(());
        }
        self.directory(&destination)?;
        if fs::canonicalize(&destination).ok().as_deref() == Some(source.as_path()) {
            return Ok(());
        }
        for path in entries(&source)?.into_iter().filter(|path| path.is_dir()) {
            let name = path.file_name().unwrap();
            if !claude
                && [
                    "agents-orchestrator",
                    "agents-worker",
                    "agents-thread",
                    "agents-watch",
                ]
                .iter()
                .any(|n| name == OsStr::new(n))
            {
                continue;
            }
            self.link(&path, &destination.join(name), claude)?;
        }
        Ok(())
    }

    fn codex(&mut self, shared: &Path) -> Result<()> {
        let profile = env::var_os("CODEX_HOME")
            .filter(|value| !value.is_empty())
            .map_or_else(|| self.home.join(".codex"), PathBuf::from);
        self.directory(&profile)?;
        if shared.join("AGENTS.md").is_file() {
            self.link(&shared.join("AGENTS.md"), &profile.join("AGENTS.md"), false)?;
        }
        self.skills(shared, &self.home.join(".agents"), false)
    }

    fn claude(&mut self, configs: &Path, shared: &Path) -> Result<()> {
        let source = configs.join("claude");
        let home = self.home.join(".claude");
        self.directory(&home)?;
        for file in entries(&source)?.into_iter().filter(|path| path.is_file()) {
            let name = file.file_name().unwrap().to_string_lossy();
            if name.starts_with("settings") || name.ends_with(".bak") || name.contains(".bak.") {
                continue;
            }
            self.link(&file, &home.join(name.as_ref()), true)?;
            if file.extension() == Some(OsStr::new("sh")) {
                self.make_executable(&file)?;
            }
        }
        self.claude_settings(&source, &home)?;
        if shared.join("AGENTS.md").is_file() {
            self.link(&shared.join("AGENTS.md"), &home.join("CLAUDE.md"), true)?;
        }
        self.skills(shared, &home, true)?;
        let hooks = home.join("hooks");
        if shared.join("hooks").is_dir() {
            let dangling = kind(&hooks)? == Kind::Link && !hooks.exists();
            if dangling {
                self.change(format!(
                    "back up dangling link {} and replace it with a directory",
                    hooks.display()
                ));
                if !self.dry_run {
                    let backup = private_dir(&home, "hooks.bak.")?;
                    fs::rename(&hooks, backup.join("link"))?;
                }
            }
            if !self.dry_run || !dangling {
                self.directory(&hooks)?;
            }
            if fs::canonicalize(&hooks).ok().as_deref() != Some(shared.join("hooks").as_path()) {
                for path in entries(&shared.join("hooks"))?
                    .into_iter()
                    .filter(|path| path.is_file())
                {
                    let destination = hooks.join(path.file_name().unwrap());
                    if self.dry_run && dangling {
                        self.change(format!(
                            "link {} -> {}",
                            destination.display(),
                            path.display()
                        ));
                    } else {
                        self.link(&path, &destination, true)?;
                    }
                    self.make_executable(&path)?;
                }
            }
        }
        Ok(())
    }

    fn make_executable(&mut self, path: &Path) -> Result<()> {
        let mut permissions = fs::metadata(path)?.permissions();
        if permissions.mode() & 0o100 == 0 {
            self.change(format!("chmod +x {}", path.display()));
            if !self.dry_run {
                permissions.set_mode(permissions.mode() | 0o100);
                fs::set_permissions(path, permissions)?;
            }
        }
        Ok(())
    }

    fn claude_settings(&mut self, source: &Path, home: &Path) -> Result<()> {
        let base = source.join("settings.json");
        if !base.is_file() {
            return Ok(());
        }
        let local = source.join("settings.local.json");
        let destination = home.join("settings.json");
        let snapshot = home.join("settings.json.generated");
        let mut value = read_json(&base)?;
        if local.is_file() {
            merge(&mut value, read_json(&local)?);
        }
        let formatted = format!(
            "{}\n",
            serde_json::to_string_pretty(&value).map_err(|error| at(&base, error))?
        );
        let current_kind = kind(&destination)?;
        let current = (current_kind == Kind::File)
            .then(|| fs::read(&destination))
            .transpose()?;
        let previous = if kind(&snapshot)? == Kind::File {
            Some(fs::read(&snapshot)?)
        } else {
            None
        };
        let matching = current
            .as_deref()
            .and_then(|bytes| serde_json::from_slice::<Value>(bytes).ok())
            .as_ref()
            == Some(&value);
        if !matches!(current_kind, Kind::Missing | Kind::Link | Kind::File) {
            self.skip(format!(
                "{} is not a regular file; left it in place",
                destination.display()
            ));
        } else if matching {
            if current != previous {
                self.change(format!("update snapshot {}", snapshot.display()));
                if !self.dry_run {
                    write_atomic(&snapshot, current.as_deref().unwrap(), 0o600)?;
                }
            }
        } else {
            let diff = current
                .as_deref()
                .map(|bytes| json_diff(bytes, &value))
                .unwrap_or_default();
            let edited = current.is_some() && current != previous;
            if edited && self.links_only {
                self.skip(format!("{} was changed outside setup; not overwriting it. Regenerating would change:\n{diff}", destination.display()));
            } else {
                if edited && !self.dry_run {
                    let backup_dir = private_dir(home, "settings.json.bak.")?;
                    let backup = backup_dir.join("settings.json");
                    write_atomic(&backup, current.as_deref().unwrap(), 0o600)?;
                    eprintln!("Backed up existing Claude settings to {}", backup.display());
                }
                let action = match current_kind {
                    Kind::Link => format!(
                        "replace symlink {} with generated settings",
                        destination.display()
                    ),
                    Kind::File => format!("rewrite {}:\n{diff}", destination.display()),
                    _ => format!("write {}", destination.display()),
                };
                self.change(action);
                if !self.dry_run {
                    write_atomic(&destination, formatted.as_bytes(), 0o600)?;
                    write_atomic(&snapshot, formatted.as_bytes(), 0o600)?;
                }
            }
        }
        let old_local = home.join("settings.local.json");
        if kind(&old_local)? == Kind::Link && fs::read_link(&old_local)? == local {
            self.change(format!("remove {}", old_local.display()));
            if !self.dry_run {
                fs::remove_file(old_local)?;
            }
        }
        Ok(())
    }
}

fn read_json(path: &Path) -> Result<Value> {
    let bytes = fs::read(path).map_err(|error| at(path, error))?;
    serde_json::from_slice(&bytes).map_err(|error| at(path, error))
}

fn merge(base: &mut Value, local: Value) {
    match (base, local) {
        (Value::Object(base), Value::Object(local)) => {
            for (key, item) in local {
                if let Some(slot) = base.get_mut(&key) {
                    merge(slot, item);
                } else {
                    base.insert(key, item);
                }
            }
        }
        (Value::Array(base), Value::Array(local)) => {
            for item in local {
                if !base.contains(&item) {
                    base.push(item);
                }
            }
        }
        (base, local) => *base = local,
    }
}

fn json_diff(bytes: &[u8], new: &Value) -> String {
    fn describe(value: &Value) -> String {
        let text = match value {
            Value::Array(items) => format!(
                "[{}]",
                items.iter().map(describe).collect::<Vec<_>>().join(", ")
            ),
            Value::Object(items) => format!(
                "{{{}}}",
                items
                    .iter()
                    .map(|(key, item)| {
                        format!("{}: {}", Value::String(key.clone()), describe(item))
                    })
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
            _ => value.to_string(),
        };
        if text.chars().count() > 80 {
            text.chars().take(77).collect::<String>() + "..."
        } else {
            text
        }
    }
    fn visit(old: &Value, new: &Value, path: &str, out: &mut Vec<String>) {
        if out.len() >= 20 || old == new {
            return;
        }
        if let (Value::Object(old), Value::Object(new)) = (old, new) {
            for (key, item) in new {
                let name = if path.is_empty() {
                    key.clone()
                } else {
                    format!("{path}.{key}")
                };
                if let Some(old) = old.get(key) {
                    visit(old, item, &name, out);
                } else {
                    out.push(format!("    + {name}: {}", describe(item)));
                }
            }
            for name in old.keys().filter(|key| !new.contains_key(*key)) {
                let name = if path.is_empty() {
                    name.clone()
                } else {
                    format!("{path}.{name}")
                };
                out.push(format!("    - {name}"));
            }
        } else {
            out.push(format!(
                "    ~ {path}: {} -> {}",
                describe(old),
                describe(new)
            ));
        }
    }
    let mut out = Vec::new();
    match serde_json::from_slice(bytes) {
        Ok(old) => visit(&old, new, "", &mut out),
        Err(_) => out.push("    ~ (current file is not valid JSON)".into()),
    }
    out.truncate(20);
    out.join("\n")
}
