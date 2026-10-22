//! Engine Manager — QuranCaption-style direct process execution.
//!
//! NO FastAPI server. NO ports. NO HTTP.
//!
//! Rust owns:
//!   - Python env resolution (system → portable download → venv)
//!   - pip streaming install
//!   - Model downloads
//!   - Spawning run.py directly and forwarding stdout/stderr as Tauri events

use std::fs;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use lazy_static::lazy_static;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};

use crate::process_utils::{configure_command_no_window, sanitize_cmd_error};

pub const MIN_PYTHON_MAJOR: u8 = 3;
pub const MIN_PYTHON_MINOR: u8 = 10;
pub const MAX_PYTHON_MINOR: u8 = 12;

// ── Global state ─────────────────────────────────────────────────────────────

struct EngineGlobalState {
    /// The active alignment child process (if any).
    child: Mutex<Option<Child>>,
    ready: AtomicBool,
    progress: Mutex<u8>,
    python_exe: Mutex<String>,
    status_message: Mutex<String>,
}

lazy_static! {
    static ref STATE: EngineGlobalState = EngineGlobalState {
        child: Mutex::new(None),
        ready: AtomicBool::new(false),
        progress: Mutex::new(0),
        python_exe: Mutex::new(String::new()),
        status_message: Mutex::new("Engine uninitialized".to_string()),
    };
}

// ── Status helpers ────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EngineStatus {
    pub ready: bool,
    pub python: String,
    pub message: String,
}

pub fn get_engine_status() -> EngineStatus {
    EngineStatus {
        ready: STATE.ready.load(Ordering::Relaxed),
        python: STATE.python_exe.lock().unwrap().clone(),
        message: STATE.status_message.lock().unwrap().clone(),
    }
}

pub fn set_status_progress(app: Option<&AppHandle>, msg: &str, progress: u8, ready: bool) {
    if let Ok(mut m) = STATE.status_message.lock() {
        *m = msg.to_string();
    }
    STATE.ready.store(ready, Ordering::Relaxed);

    let mut eff_p = progress;
    if let Ok(mut p) = STATE.progress.lock() {
        if ready {
            *p = 100;
            eff_p = 100;
        } else if progress > *p {
            *p = progress;
            eff_p = progress;
        } else {
            eff_p = *p;
        }
    }

    if let Some(handle) = app {
        let _ = handle.emit(
            "engine-status",
            serde_json::json!({
                "ready": ready,
                "message": msg,
                "progress": eff_p
            }),
        );
        let _ = handle.emit(
            "install-status",
            serde_json::json!({
                "message": msg,
                "progress": eff_p,
                "ready": ready
            }),
        );
    }
}

pub fn set_status_error(app: &AppHandle, err_msg: &str) {
    if let Ok(mut m) = STATE.status_message.lock() {
        *m = err_msg.to_string();
    }
    STATE.ready.store(false, Ordering::Relaxed);
    let _ = app.emit(
        "install-status",
        serde_json::json!({
            "message": format!("Setup error: {}", err_msg),
            "progress": 0,
            "ready": false,
            "error": err_msg
        }),
    );
}

#[allow(dead_code)]
pub fn set_status(app: Option<&AppHandle>, msg: &str, ready: bool) {
    let p = if ready { 100 } else { *STATE.progress.lock().unwrap() };
    set_status_progress(app, msg, p, ready);
}

// ── Python resolution ─────────────────────────────────────────────────────────

/// Runs a command with a hard timeout, capturing stdout/stderr.
///
/// Some interpreter candidates (notably the Microsoft Store `python.exe` /
/// `python3.exe` App Execution Aliases) can hang or open the Store window
/// instead of exiting, which would otherwise stall engine startup for minutes.
fn run_command_with_timeout(cmd: &mut Command, timeout: Duration) -> Option<std::process::Output> {
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());
    let mut child = cmd.spawn().ok()?;
    let started = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return child.wait_with_output().ok(),
            Ok(None) => {
                if started.elapsed() > timeout {
                    let _ = child.kill();
                    let _ = child.wait();
                    return None;
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            Err(_) => {
                let _ = child.kill();
                return None;
            }
        }
    }
}

/// Detects the tiny Microsoft Store "App Execution Alias" stubs on PATH
/// (e.g. `%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`). Launching them
/// can pop up the Microsoft Store and stall for a long time, so they are
/// skipped while probing for a usable system Python.
fn is_windows_store_stub_alias(name: &str) -> bool {
    #[cfg(target_os = "windows")]
    {
        let exe_name = format!("{}.exe", name);
        let path_var = std::env::var("PATH").unwrap_or_default();
        for dir in path_var.split(';') {
            let trimmed = dir.trim();
            if trimmed.is_empty() {
                continue;
            }
            let candidate = Path::new(trimmed).join(&exe_name);
            if candidate.is_file() {
                let len = fs::metadata(&candidate).map(|m| m.len()).unwrap_or(0);
                let lower = candidate.to_string_lossy().to_lowercase();
                return lower.contains("\\windowsapps\\") && len < 100_000;
            }
        }
        false
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = name;
        false
    }
}

pub fn read_python_version(python_exe: &Path) -> Option<(u8, u8, u8)> {
    let check_script =
        "import json,sys; print(json.dumps({'major':sys.version_info[0],'minor':sys.version_info[1],'patch':sys.version_info[2]}))";
    let mut cmd = Command::new(python_exe);
    cmd.args(["-c", check_script]);
    configure_command_no_window(&mut cmd);
    let output = run_command_with_timeout(&mut cmd, Duration::from_secs(10))?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let parsed: serde_json::Value = serde_json::from_str(&stdout).ok()?;
    Some((
        parsed.get("major")?.as_u64()? as u8,
        parsed.get("minor")?.as_u64()? as u8,
        parsed.get("patch")?.as_u64()? as u8,
    ))
}

fn python_version_meets_min(major: u8, minor: u8) -> bool {
    major == MIN_PYTHON_MAJOR && minor >= MIN_PYTHON_MINOR && minor <= MAX_PYTHON_MINOR
}

pub fn resolve_system_python() -> Option<PathBuf> {
    let candidates = if cfg!(target_os = "windows") {
        vec!["python3.12", "python3.11", "python3.10", "python3.13", "python3.14", "python", "python3"]
    } else if cfg!(target_os = "macos") {
        vec![
            "/opt/homebrew/bin/python3.12",
            "/opt/homebrew/bin/python3.11",
            "/opt/homebrew/bin/python3.10",
            "/opt/homebrew/bin/python3.13",
            "/usr/local/bin/python3.12",
            "/usr/local/bin/python3.11",
            "python3.12",
            "python3.11",
            "python3",
            "python",
        ]
    } else {
        vec!["python3.12", "python3.11", "python3.10", "python3.13", "python3", "python"]
    };

    for candidate in candidates {
        // Skip broken Microsoft Store aliases that hang or open the Store.
        if is_windows_store_stub_alias(candidate) {
            continue;
        }
        let mut cmd = Command::new(candidate);
        cmd.args(["-c", "import sys; print(sys.executable)"]);
        configure_command_no_window(&mut cmd);
        if let Some(output) = run_command_with_timeout(&mut cmd, Duration::from_secs(10)) {
            if output.status.success() {
                let exe_str = String::from_utf8_lossy(&output.stdout).trim().to_string();
                let exe_path = PathBuf::from(&exe_str);
                if let Some((major, minor, _)) = read_python_version(&exe_path) {
                    if python_version_meets_min(major, minor) {
                        return Some(exe_path);
                    }
                }
            }
        }
    }
    None
}

pub fn get_portable_python_root(app_handle: &AppHandle) -> Result<PathBuf, String> {
    let app_data = app_handle
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?;
    Ok(app_data.join("python_runtime"))
}

pub fn get_portable_python_exe(app_handle: &AppHandle) -> Result<PathBuf, String> {
    let root = get_portable_python_root(app_handle)?;
    let expected = if cfg!(target_os = "windows") {
        root.join("python").join("python.exe")
    } else {
        root.join("python").join("bin").join("python3")
    };
    if expected.exists() {
        return Ok(expected);
    }
    let direct = if cfg!(target_os = "windows") {
        root.join("python.exe")
    } else {
        root.join("bin").join("python3")
    };
    if direct.exists() {
        return Ok(direct);
    }
    Ok(expected)
}

pub fn get_portable_python_download_info() -> Result<(&'static str, &'static str), String> {
    if cfg!(target_os = "windows") {
        Ok((
            "https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.11.10%2B20241016-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
            "cpython-3.11-windows-x64.tar.gz",
        ))
    } else if cfg!(target_os = "macos") {
        if cfg!(target_arch = "aarch64") {
            Ok((
                "https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.11.10%2B20241016-aarch64-apple-darwin-install_only_stripped.tar.gz",
                "cpython-3.11-macos-arm64.tar.gz",
            ))
        } else {
            Ok((
                "https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.11.10%2B20241016-x86_64-apple-darwin-install_only_stripped.tar.gz",
                "cpython-3.11-macos-x64.tar.gz",
            ))
        }
    } else if cfg!(target_os = "linux") {
        Ok((
            "https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.11.10%2B20241016-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
            "cpython-3.11-linux-x64.tar.gz",
        ))
    } else {
        Err("Unsupported operating system for portable Python.".to_string())
    }
}

// ── Download helper ───────────────────────────────────────────────────────────

async fn download_binary_file<F>(
    url: &str,
    destination_path: &Path,
    mut on_progress: F,
) -> Result<(), String>
where
    F: FnMut(u64, Option<u64>),
{
    let response = reqwest::get(url)
        .await
        .map_err(|e| format!("Failed to download '{}': {}", url, e))?;
    if !response.status().is_success() {
        return Err(format!(
            "Failed to download '{}': HTTP {}",
            url,
            response.status()
        ));
    }

    let total = response.content_length();
    let mut downloaded = 0u64;
    on_progress(0, total);

    let temp_path = destination_path.with_extension("download");
    let mut file = tokio::fs::File::create(&temp_path)
        .await
        .map_err(|e| format!("Failed to create file: {}", e))?;

    let mut response = response;
    let mut last_emit = std::time::Instant::now();
    use tokio::io::AsyncWriteExt;
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|e| format!("Failed to read chunk from '{}': {}", url, e))?
    {
        file.write_all(&chunk)
            .await
            .map_err(|e| format!("Failed to write chunk: {}", e))?;
        downloaded += chunk.len() as u64;
        if last_emit.elapsed() >= std::time::Duration::from_millis(150) {
            on_progress(downloaded, total);
            last_emit = std::time::Instant::now();
        }
    }
    file.flush()
        .await
        .map_err(|e| format!("Failed to flush: {}", e))?;
    drop(file);

    on_progress(downloaded, total.or(Some(downloaded)));

    if downloaded == 0 {
        let _ = tokio::fs::remove_file(&temp_path).await;
        return Err(format!("Downloaded file from '{}' is empty", url));
    }

    tokio::fs::rename(&temp_path, destination_path)
        .await
        .map_err(|e| format!("Failed to rename temp download: {}", e))?;

    Ok(())
}

// ── Portable Python runtime ───────────────────────────────────────────────────

pub async fn ensure_portable_python_runtime(app_handle: &AppHandle) -> Result<PathBuf, String> {
    let portable_root = get_portable_python_root(app_handle)?;
    let portable_exe = get_portable_python_exe(app_handle)?;
    if portable_exe.exists() {
        if let Some((major, minor, _)) = read_python_version(&portable_exe) {
            if python_version_meets_min(major, minor) {
                let mut check_pip = Command::new(&portable_exe);
                check_pip.args(["-m", "pip", "--version"]);
                configure_command_no_window(&mut check_pip);
                if let Ok(p_out) = check_pip.output() {
                    if p_out.status.success() {
                        return Ok(portable_exe);
                    }
                }
            }
        }
        let python_dir = portable_root.join("python");
        let _ = fs::remove_dir_all(&python_dir);
    }

    fs::create_dir_all(&portable_root).map_err(|e| {
        format!(
            "Failed to create portable Python directory '{}': {}",
            portable_root.to_string_lossy(),
            e
        )
    })?;

    let (url, file_name) = get_portable_python_download_info()?;
    let archive_path = portable_root.join(file_name);

    download_binary_file(url, &archive_path, |downloaded, total| {
        let (pct, status_text) = if let Some(tot) = total {
            let ratio = (downloaded as f32 / tot as f32).min(1.0);
            let p = 5 + (ratio * 15.0).round() as u8;
            let mb_down = downloaded as f64 / 1_048_576.0;
            let mb_tot = tot as f64 / 1_048_576.0;
            (p, format!("Downloading Python 3.11 standalone ({:.1}/{:.1} MB)...", mb_down, mb_tot))
        } else {
            let mb_down = downloaded as f64 / 1_048_576.0;
            (10, format!("Downloading Python 3.11 standalone ({:.1} MB)...", mb_down))
        };
        set_status_progress(Some(app_handle), &status_text, pct, false);
    })
    .await?;

    set_status_progress(Some(app_handle), "Extracting Python 3.11 standalone runtime...", 22, false);

    let tar_binary = if cfg!(target_os = "windows") {
        let system32_tar = std::path::Path::new("C:\\Windows\\System32\\tar.exe");
        if system32_tar.exists() {
            system32_tar.to_string_lossy().to_string()
        } else {
            "tar".to_string()
        }
    } else {
        "tar".to_string()
    };

    let mut cmd = Command::new(&tar_binary);
    cmd.args([
        "-xzf",
        archive_path.to_str().ok_or("Invalid archive path")?,
        "-C",
        portable_root.to_str().ok_or("Invalid destination path")?,
    ]);
    configure_command_no_window(&mut cmd);
    let output = cmd.output().map_err(|e| format!("Failed to extract portable Python: {}", e))?;
    let _ = fs::remove_file(&archive_path);

    if !output.status.success() {
        return Err(format!(
            "Failed to extract portable Python: {}",
            sanitize_cmd_error(&output)
        ));
    }

    let portable_exe = get_portable_python_exe(app_handle)?;
    if !portable_exe.exists() || read_python_version(&portable_exe).is_none() {
        return Err(format!(
            "Portable Python extracted but executable was not found or invalid at {}",
            portable_exe.to_string_lossy()
        ));
    }

    set_status_progress(Some(app_handle), "Python 3.11 standalone runtime ready.", 25, false);
    Ok(portable_exe)
}

// ── Venv ──────────────────────────────────────────────────────────────────────

pub fn get_engine_venv_path(app_handle: &AppHandle) -> Result<PathBuf, String> {
    let app_data = app_handle
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?;
    Ok(app_data.join("python_env"))
}

pub fn get_venv_python_exe(venv_dir: &Path) -> PathBuf {
    if cfg!(target_os = "windows") {
        venv_dir.join("Scripts").join("python.exe")
    } else {
        venv_dir.join("bin").join("python3")
    }
}

pub fn create_venv_if_missing(app_handle: &AppHandle, base_python: &Path) -> Result<PathBuf, String> {
    let venv_dir = get_engine_venv_path(app_handle)?;
    let python_exe = get_venv_python_exe(&venv_dir);

    if python_exe.exists() {
        if let Some((major, minor, _)) = read_python_version(&python_exe) {
            if python_version_meets_min(major, minor) {
                return Ok(venv_dir);
            }
        }
        let _ = fs::remove_dir_all(&venv_dir);
    }

    set_status_progress(Some(app_handle), "Creating isolated Python environment...", 26, false);

    let mut cmd = Command::new(base_python);
    cmd.args(["-m", "venv", "--system-site-packages", venv_dir.to_string_lossy().as_ref()]);
    configure_command_no_window(&mut cmd);

    let output = cmd.output().map_err(|e| format!("Failed to run venv: {}", e))?;
    if !output.status.success() {
        let mut venv_cmd = Command::new(base_python);
        venv_cmd.args(["-m", "virtualenv", venv_dir.to_string_lossy().as_ref()]);
        configure_command_no_window(&mut venv_cmd);
        let venv_output = venv_cmd.output().map_err(|e| format!("Failed to run virtualenv: {}", e))?;
        if !venv_output.status.success() {
            return Err(format!(
                "Failed to create Python virtual environment: {}",
                sanitize_cmd_error(&venv_output)
            ));
        }
    }

    if !python_exe.exists() {
        return Err(format!(
            "Python environment created but binary not found at {}",
            python_exe.display()
        ));
    }

    Ok(venv_dir)
}

// ── pip streaming install ─────────────────────────────────────────────────────

fn run_pip_install_streaming<F>(
    python_exe: &Path,
    args: &[&str],
    emit_progress: &F,
    start_pct: u8,
    end_pct: u8,
    context: &str,
) -> Result<(), String>
where
    F: Fn(&str, u8),
{
    let mut cmd = Command::new(python_exe);
    cmd.arg("-m")
        .arg("pip")
        .arg("install")
        .arg("--prefer-binary")
        .arg("--no-compile")
        .arg("--progress-bar")
        .arg("off")
        .arg("--no-input");
    cmd.args(args);

    configure_command_no_window(&mut cmd);
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("{}: failed to run pip: {}", context, e))?;

    let stdout = child.stdout.take().ok_or("Failed to capture stdout")?;
    let stderr = child.stderr.take().ok_or("Failed to capture stderr")?;

    let stderr_lines = Arc::new(Mutex::new(Vec::<String>::new()));
    let stderr_lines_clone = Arc::clone(&stderr_lines);
    let stderr_handle = std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines().flatten() {
            if let Ok(mut l) = stderr_lines_clone.lock() {
                l.push(line);
            }
        }
    });

    let span = end_pct.saturating_sub(start_pct).max(1) as f32;
    let mut step_count: u32 = 0;

    let reader = BufReader::new(stdout);
    let mut output_lines: Vec<String> = Vec::new();

    for line in reader.lines().flatten() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        output_lines.push(trimmed.to_string());

        if trimmed.starts_with("Collecting ") {
            step_count += 1;
            let pkg_spec = trimmed.trim_start_matches("Collecting ").trim();
            let pkg_name = pkg_spec
                .split(|c: char| c == '=' || c == '<' || c == '>' || c == '~' || c.is_whitespace())
                .next()
                .unwrap_or(pkg_spec);
            let pct = (start_pct as f32 + (step_count as f32 * 1.5).min(span - 2.0)) as u8;
            emit_progress(&format!("Downloading package: {}...", pkg_name), pct);
        } else if trimmed.starts_with("Downloading ") {
            let file_info = trimmed.trim_start_matches("Downloading ").trim();
            let short_info = if let Some(open_paren) = file_info.find('(') {
                let fname = file_info[..open_paren].trim();
                let size = &file_info[open_paren..];
                let simple_name = fname.split('-').next().unwrap_or(fname);
                format!("{} {}", simple_name, size)
            } else {
                file_info.to_string()
            };
            step_count += 1;
            let pct = (start_pct as f32 + (step_count as f32 * 1.5).min(span - 2.0)) as u8;
            emit_progress(&format!("Downloading: {}...", short_info), pct);
        } else if trimmed.starts_with("Installing collected packages:") {
            emit_progress(
                "Installing downloaded packages into environment...",
                end_pct.saturating_sub(1),
            );
        } else if trimmed.starts_with("Successfully installed ") {
            emit_progress("Packages installed successfully.", end_pct);
        }
    }

    let _ = stderr_handle.join();
    let status = child
        .wait()
        .map_err(|e| format!("{}: failed to wait on pip: {}", context, e))?;

    if !status.success() {
        let err_vec = stderr_lines.lock().map(|l| l.clone()).unwrap_or_default();
        let last_err = if !err_vec.is_empty() {
            err_vec.join("\n")
        } else {
            output_lines.join("\n")
        };
        return Err(format!("{}: {}", context, last_err));
    }

    emit_progress("Python packages ready.", end_pct);
    Ok(())
}

pub fn ensure_dependencies(app_handle: &AppHandle, python_exe: &Path) -> Result<(), String> {
    // Check if core packages are already installed
    let check_script = r#"
import sys
for mod in ["numpy", "onnxruntime", "numba", "scipy", "miniaudio"]:
    try:
        __import__(mod)
    except ImportError:
        sys.exit(1)
sys.exit(0)
"#;
    let mut check_cmd = Command::new(python_exe);
    check_cmd.args(["-c", check_script]);
    configure_command_no_window(&mut check_cmd);
    if let Ok(out) = check_cmd.output() {
        if out.status.success() {
            return Ok(());
        }
    }

    set_status_progress(Some(app_handle), "Resolving dependencies via pip...", 30, false);

    let packages = [
        "numpy",
        "onnxruntime",
        "numba",
        "miniaudio",
        "scipy",
        "requests",
    ];

    let emit = |msg: &str, pct: u8| {
        set_status_progress(Some(app_handle), msg, pct, false);
    };

    run_pip_install_streaming(
        python_exe,
        &packages,
        &emit,
        30,
        85,
        "Failed to install Python dependencies",
    )?;

    set_status_progress(Some(app_handle), "All dependencies installed successfully", 85, false);
    Ok(())
}

// ── Project root resolution ───────────────────────────────────────────────────

/// Locates the repository root containing `run.py`.
pub fn resolve_project_root(app_handle: &AppHandle) -> Result<PathBuf, String> {
    // 1. Bundled resources
    if let Ok(res_dir) = app_handle.path().resource_dir() {
        if res_dir.join("run.py").exists() {
            return Ok(res_dir);
        }
    }

    // 2. Dev: walk up from executable
    if let Ok(exe_path) = std::env::current_exe() {
        for ancestor in exe_path.ancestors().skip(1).take(6) {
            if ancestor.join("run.py").exists() {
                return Ok(ancestor.to_path_buf());
            }
            if ancestor.join("app").join("src-tauri").exists() {
                // We are inside the app dir; project root is one level up
                if let Some(parent) = ancestor.parent() {
                    if parent.join("run.py").exists() {
                        return Ok(parent.to_path_buf());
                    }
                }
            }
        }
    }

    // 3. CWD
    if let Ok(cwd) = std::env::current_dir() {
        if cwd.join("run.py").exists() {
            return Ok(cwd);
        }
        // If CWD is the `app/` folder
        if let Some(parent) = cwd.parent() {
            if parent.join("run.py").exists() {
                return Ok(parent.to_path_buf());
            }
        }
    }

    Err("Could not locate run.py (QuranReciteToText project root)".to_string())
}

// ── Model downloads ───────────────────────────────────────────────────────────

pub async fn ensure_engine_models(app_handle: &AppHandle) -> Result<(), String> {
    let project_root = resolve_project_root(app_handle)?;
    let onnx_dir = project_root.join("data").join("onnx");
    fs::create_dir_all(&onnx_dir).map_err(|e| format!("Failed to create onnx dir: {}", e))?;

    let vad_path = onnx_dir.join("silero_vad_half.onnx");
    let needs_vad = match fs::metadata(&vad_path) {
        Ok(m) => m.len() < 500_000,
        Err(_) => true,
    };
    if needs_vad {
        set_status_progress(Some(app_handle), "Downloading Silero VAD speech detector (~1.3 MB)...", 86, false);
        let vad_url = "https://raw.githubusercontent.com/snakers4/silero-vad/1e261b036686cd0017d500ee96acd1c4ba572a9d/src/silero_vad/data/silero_vad_half.onnx";
        download_binary_file(vad_url, &vad_path, |_, _| {}).await?;
    }

    let zipformer_path = onnx_dir.join("zipformer_p_arabic_v3.int8.onnx");
    let needs_zipformer = match fs::metadata(&zipformer_path) {
        Ok(m) => m.len() < 10_000_000,
        Err(_) => true,
    };
    if needs_zipformer {
        let zipformer_url = "https://github.com/Iam-Muslim/Natlu/releases/download/models-latest/zipformer_p_arabic_v3.int8.onnx";
        let temp_path = onnx_dir.join("zipformer_p_arabic_v3.int8.onnx.download");
        download_binary_file(zipformer_url, &temp_path, |downloaded, total| {
            let (pct, status_text) = if let Some(tot) = total {
                let ratio = (downloaded as f32 / tot as f32).min(1.0);
                let p = 86 + (ratio * 10.0).round() as u8;
                let mb_down = downloaded as f64 / 1_048_576.0;
                let mb_tot = tot as f64 / 1_048_576.0;
                (p, format!("Downloading Zipformer acoustic model ({:.1}/{:.1} MB)...", mb_down, mb_tot))
            } else {
                let mb_down = downloaded as f64 / 1_048_576.0;
                (88, format!("Downloading Zipformer acoustic model ({:.1} MB)...", mb_down))
            };
            set_status_progress(Some(app_handle), &status_text, pct, false);
        }).await?;

        if temp_path.exists() {
            if zipformer_path.exists() {
                let _ = fs::remove_file(&zipformer_path);
            }
            fs::rename(&temp_path, &zipformer_path).map_err(|e| format!("Failed to save Zipformer model: {}", e))?;
        }
    }

    Ok(())
}

// ── Environment check ─────────────────────────────────────────────────────────

pub fn is_environment_fully_installed(app_handle: &AppHandle) -> bool {
    let project_root = match resolve_project_root(app_handle) {
        Ok(r) => r,
        Err(_) => return false,
    };
    let onnx_dir = project_root.join("data").join("onnx");
    let vad_path = onnx_dir.join("silero_vad_half.onnx");
    let zipformer_path = onnx_dir.join("zipformer_p_arabic_v3.int8.onnx");

    let vad_ok = fs::metadata(&vad_path).map(|m| m.len() > 500_000).unwrap_or(false);
    let zipformer_ok = fs::metadata(&zipformer_path).map(|m| m.len() > 10_000_000).unwrap_or(false);

    let venv_dir = match get_engine_venv_path(app_handle) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let venv_python = get_venv_python_exe(&venv_dir);

    vad_ok && zipformer_ok && venv_python.exists()
}

// ── Engine initialization (QuranCaption pattern) ──────────────────────────────

/// Initializes the Python environment. No server is started.
/// After this, the engine is "ready" — the UI can invoke `run_align`.
///
/// `force = false` (normal app boot) takes a fast path when the environment
/// is already installed: no interpreter probing, no pip audit, no bootstrap
/// spawns. `force = true` (install/repair flows) always performs the full
/// verification.
pub async fn start_engine(app_handle: AppHandle, force: bool) -> Result<(), String> {
    let already_installed = is_environment_fully_installed(&app_handle);

    // ── Fast path: everything is in place — zero subprocess work ──────────────
    if !force && already_installed {
        let venv_dir = get_engine_venv_path(&app_handle)?;
        let venv_exe = get_venv_python_exe(&venv_dir);
        if venv_exe.exists() {
            *STATE.python_exe.lock().unwrap() = venv_exe.to_string_lossy().to_string();
            set_status_progress(Some(&app_handle), "Alignment Engine Ready", 100, true);
            return Ok(());
        }
    }

    if !already_installed {
        set_status_progress(Some(&app_handle), "Resolving Python environment...", 5, false);
    }

    // 1. Resolve base Python (system → portable download)
    let base_python = match resolve_system_python() {
        Some(sys) => sys,
        None => ensure_portable_python_runtime(&app_handle).await?,
    };

    // 2. Create isolated venv (QuranCaption pattern)
    let venv_dir = create_venv_if_missing(&app_handle, &base_python)?;
    let venv_python_exe = get_venv_python_exe(&venv_dir);
    *STATE.python_exe.lock().unwrap() = venv_python_exe.to_string_lossy().to_string();

    // 3. pip install with streaming progress
    ensure_dependencies(&app_handle, &venv_python_exe)?;

    let project_root = resolve_project_root(&app_handle)?;

    // 4. Bootstrap DLLs on Windows (exact QuranCaption pattern)
    if cfg!(target_os = "windows") {
        let run_script = project_root.join("run.py");
        if run_script.exists() {
            let mut init_cmd = Command::new(&venv_python_exe);
            init_cmd.arg(&run_script).arg("--help");
            init_cmd.current_dir(&project_root);
            configure_command_no_window(&mut init_cmd);
            let _ = init_cmd.output();
        }
    }

    // 5. Download ONNX models
    ensure_engine_models(&app_handle).await?;

    // 6. Mark ready — no server needed
    set_status_progress(Some(&app_handle), "Alignment Engine Ready", 100, true);
    Ok(())
}

// ── Alignment — direct process execution (QuranCaption pattern) ───────────────

/// Robustly extracts the final JSON payload from stdout, ignoring any leading prints or warnings.
fn extract_json_payload(stdout_buffer: &str) -> Result<serde_json::Value, String> {
    // 1. Try reverse line-by-line parsing to locate the final JSON payload
    for line in stdout_buffer.lines().rev() {
        let trimmed = line.trim();
        if (trimmed.starts_with('{') && trimmed.ends_with('}'))
            || (trimmed.starts_with('[') && trimmed.ends_with(']'))
        {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(trimmed) {
                if val.get("surahs").is_some()
                    || val.get("segments").is_some()
                    || val.get("total_files").is_some()
                    || val.get("error").is_some()
                {
                    return Ok(val);
                }
            }
        }
    }

    // 2. Fallback: stream-deserialize any valid JSON objects found anywhere in buffer
    let mut last_val: Option<serde_json::Value> = None;
    for res in serde_json::Deserializer::from_str(stdout_buffer).into_iter::<serde_json::Value>() {
        if let Ok(val) = res {
            if val.get("surahs").is_some()
                || val.get("segments").is_some()
                || val.get("total_files").is_some()
                || val.get("error").is_some()
            {
                return Ok(val);
            }
            last_val = Some(val);
        }
    }

    if let Some(val) = last_val {
        return Ok(val);
    }

    Err("Python script returned no JSON output".to_string())
}

/// Spawns `run.py` directly and streams stdout/stderr as Tauri events.
/// stdout lines are forwarded as `align-event` with `{type: "progress", data: <json>}`.
/// stderr lines are forwarded as `align-event` with `{type: "stderr", text: <str>}`.
/// On completion or error an `align-event` with `type: "complete"` or `"error"` is emitted.
pub fn run_alignment(
    app_handle: AppHandle,
    audio_path: Option<String>,
    dir_path: Option<String>,
    fast: bool,
    qiraat: Option<String>,
) -> Result<(), String> {
    // Kill any running alignment first
    stop_engine();

    let mut python_exe_str = STATE.python_exe.lock().unwrap().clone();
    if python_exe_str.is_empty() {
        if let Ok(venv_dir) = get_engine_venv_path(&app_handle) {
            let venv_exe = get_venv_python_exe(&venv_dir);
            if venv_exe.exists() {
                python_exe_str = venv_exe.to_string_lossy().to_string();
                *STATE.python_exe.lock().unwrap() = python_exe_str.clone();
            }
        }
        if python_exe_str.is_empty() {
            if let Some(sys_exe) = resolve_system_python() {
                python_exe_str = sys_exe.to_string_lossy().to_string();
                *STATE.python_exe.lock().unwrap() = python_exe_str.clone();
            }
        }
    }
    if python_exe_str.is_empty() {
        return Err("Python environment not ready. Please wait for setup to complete.".to_string());
    }
    let python_exe = PathBuf::from(&python_exe_str);
    if !python_exe.exists() {
        return Err(format!("Python executable not found: {}", python_exe_str));
    }

    let project_root = resolve_project_root(&app_handle)?;

    // Resolve local_word_timing_segmenter.py script path (QuranCaption pattern)
    let script_py = {
        let candidates = [
            app_handle.path().resolve("python/local_word_timing_segmenter.py", tauri::path::BaseDirectory::Resource).unwrap_or_default(),
            app_handle.path().resolve("python/align_bridge.py", tauri::path::BaseDirectory::Resource).unwrap_or_default(),
            project_root.join("app").join("src-tauri").join("python").join("local_word_timing_segmenter.py"),
            project_root.join("app").join("src-tauri").join("python").join("align_bridge.py"),
            project_root.join("src-tauri").join("python").join("local_word_timing_segmenter.py"),
        ];
        candidates.into_iter().find(|p| p.is_file()).ok_or_else(|| {
            format!("Could not locate local_word_timing_segmenter.py in project: {}", project_root.display())
        })?
    };

    let mut cmd_args: Vec<String> = vec![script_py.to_string_lossy().to_string()];

    if let Some(ref dir) = dir_path {
        cmd_args.push("--dir".to_string());
        cmd_args.push(dir.clone());
    } else if let Some(ref audio) = audio_path {
        cmd_args.push(audio.clone());
    } else {
        return Err("Either audio_path or dir_path must be provided.".to_string());
    }

    if fast {
        cmd_args.push("--fast".to_string());
    }

    if let Some(ref q) = qiraat {
        let q_trimmed = q.trim();
        if !q_trimmed.is_empty() {
            cmd_args.push("--qiraat".to_string());
            cmd_args.push(q_trimmed.to_lowercase());
        }
    }

    // Environment matching QuranCaption
    let path_var = std::env::var("PATH").unwrap_or_default();
    let sep = if cfg!(target_os = "windows") { ";" } else { ":" };
    let data_bin_dir = project_root.join("data").join("bin");
    let new_path = if data_bin_dir.exists() {
        format!("{}{}{}", data_bin_dir.to_string_lossy(), sep, path_var)
    } else {
        path_var
    };

    let src_dir = project_root.join("src");
    let existing_ppath = std::env::var("PYTHONPATH").unwrap_or_default();
    let python_path = if existing_ppath.is_empty() {
        format!("{}{}{}", project_root.to_string_lossy(), sep, src_dir.to_string_lossy())
    } else {
        format!("{}{}{}{}{}", project_root.to_string_lossy(), sep, src_dir.to_string_lossy(), sep, existing_ppath)
    };

    let mut cmd = Command::new(&python_exe);
    cmd.args(&cmd_args);
    cmd.current_dir(&project_root);
    cmd.env("PATH", &new_path);
    cmd.env("PYTHONUNBUFFERED", "1");
    cmd.env("PYTHONIOENCODING", "utf-8");
    cmd.env("PYTHONUTF8", "1");
    cmd.env("PYTHONFAULTHANDLER", "1");
    cmd.env("PYTHONPATH", &python_path);
    cmd.env("QURAN_PROJECT_ROOT", project_root.to_string_lossy().as_ref());
    cmd.env("OMP_WAIT_POLICY", "PASSIVE");
    cmd.env("KMP_BLOCKTIME", "0");
    cmd.env("PIP_DISABLE_PIP_VERSION_CHECK", "1");
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::piped());
    configure_command_no_window(&mut cmd);

    let display_target = dir_path.as_deref()
        .map(|d| format!("Directory: {}", PathBuf::from(d).file_name().unwrap_or_default().to_string_lossy()))
        .or_else(|| audio_path.as_deref().map(|a| PathBuf::from(a).file_name().unwrap_or_default().to_string_lossy().to_string()))
        .unwrap_or_default();

    let is_batch_dir = dir_path.is_some();
    let target_path = dir_path.clone().or_else(|| audio_path.clone()).unwrap_or_default();

    let _ = app_handle.emit(
        "align-event",
        serde_json::json!({
            "type": "start",
            "audio": display_target,
        }),
    );

    // The Python engine spends its first seconds importing NumPy/ONNX and
    // building model sessions before any real progress exists. Emit a
    // "loading" stage immediately so the UI shows live feedback from t=0.
    let _ = app_handle.emit(
        "align-event",
        serde_json::json!({
            "type": "progress",
            "data": {
                "stage": "loading",
                "progress": 4,
                "message": "Starting Python alignment engine…",
            },
        }),
    );

    let mut child = cmd.spawn().map_err(|e| format!("Failed to spawn Python segmenter: {}", e))?;

    // Capture stderr in a separate thread (QuranCaption pattern)
    let stderr_stream = child.stderr.take().ok_or("Failed to capture stderr")?;
    let stdout_stream = child.stdout.take().ok_or("Failed to capture stdout")?;

    let app_clone_stderr = app_handle.clone();
    let stderr_lines = Arc::new(Mutex::new(Vec::<String>::new()));
    let stderr_lines_clone = Arc::clone(&stderr_lines);

    let stderr_handle = std::thread::spawn(move || {
        let reader = BufReader::new(stderr_stream);
        for line in reader.lines() {
            if let Ok(line) = line {
                let trimmed = line.trim();
                if trimmed.is_empty() { continue; }
                if trimmed.starts_with("STATUS:") {
                    let json_str = trimmed.trim_start_matches("STATUS:");
                    if let Ok(status_data) = serde_json::from_str::<serde_json::Value>(json_str) {
                        let _ = app_clone_stderr.emit("segmentation-status", &status_data);
                        let _ = app_clone_stderr.emit(
                            "align-event",
                            serde_json::json!({"type": "progress", "data": status_data}),
                        );
                    }
                } else {
                    let _ = app_clone_stderr.emit(
                        "align-event",
                        serde_json::json!({"type": "stderr", "text": trimmed}),
                    );
                    if let Ok(mut l) = stderr_lines_clone.lock() {
                        l.push(trimmed.to_string());
                        if l.len() > 120 {
                            let drain = l.len() - 120;
                            l.drain(0..drain);
                        }
                    }
                }
            }
        }
    });

    // Store child for potential cancellation
    *STATE.child.lock().unwrap() = Some(child);

    // Read stdout in background thread, deserialize JSON payload directly in memory
    let app_clone_stdout = app_handle.clone();
    let target_path_for_thread = target_path.clone();

    std::thread::spawn(move || {
        let mut stdout_buffer = String::new();
        let reader = BufReader::new(stdout_stream);
        for line in reader.lines() {
            let Ok(line) = line else { break };
            stdout_buffer.push_str(&line);
            stdout_buffer.push('\n');
        }

        // Wait for child process to finish
        let exit_code = {
            let mut lock = STATE.child.lock().unwrap();
            if let Some(ref mut child) = *lock {
                child.wait().map(|s| s.code().unwrap_or(-1)).unwrap_or(-1)
            } else {
                -1
            }
        };
        *STATE.child.lock().unwrap() = None;
        let _ = stderr_handle.join();

        if exit_code == 0 {
            // Direct in-memory JSON deserialization with robust reverse scanning
            let parsed_result = extract_json_payload(&stdout_buffer);

            match parsed_result {
                Ok(result_data) => {
                    if let Some(err) = result_data.get("error").and_then(|e| e.as_str()) {
                        let _ = app_clone_stdout.emit(
                            "align-event",
                            serde_json::json!({
                                "type": "error",
                                "message": err,
                            }),
                        );
                    } else {
                        let _ = app_clone_stdout.emit(
                            "align-event",
                            serde_json::json!({
                                "type": "complete",
                                "code": exit_code,
                                "audio_url": serde_json::Value::Null,
                                "audio_path": target_path_for_thread,
                                "is_batch": is_batch_dir,
                                "result": result_data,
                            }),
                        );
                    }
                }
                Err(err) => {
                    let stderr_text = stderr_lines
                        .lock()
                        .map(|l| l.join("\n"))
                        .unwrap_or_default();
                    let msg = if stderr_text.trim().is_empty() {
                        err
                    } else {
                        format!("{} (stderr: {})", err, stderr_text.trim())
                    };
                    let _ = app_clone_stdout.emit(
                        "align-event",
                        serde_json::json!({
                            "type": "error",
                            "message": msg,
                        }),
                    );
                }
            }
        } else {
            let stderr_text = stderr_lines
                .lock()
                .map(|l| l.join("\n"))
                .unwrap_or_default();
            let _ = app_clone_stdout.emit(
                "align-event",
                serde_json::json!({
                    "type": "error",
                    "code": exit_code,
                    "message": format!("Python segmenter exited with code {}. {}", exit_code, stderr_text.trim()),
                }),
            );
        }
    });

    Ok(())
}

/// Simple URL-encoding for path strings (no external crate needed).
#[allow(dead_code)]
fn urlencoding_simple(s: &str) -> String {
    let mut encoded = String::new();
    for byte in s.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9'
            | b'-' | b'_' | b'.' | b'~' | b'/' | b':' => {
                encoded.push(byte as char);
            }
            b' ' => encoded.push_str("%20"),
            b => encoded.push_str(&format!("%{:02X}", b)),
        }
    }
    encoded
}

// ── Stop / cleanup ────────────────────────────────────────────────────────────

pub fn stop_engine() {
    if let Ok(mut lock) = STATE.child.lock() {
        if let Some(mut child) = lock.take() {
            #[cfg(target_os = "windows")]
            {
                let pid = child.id();
                let _ = Command::new("taskkill")
                    .args(["/pid", &pid.to_string(), "/T", "/F"])
                    .output();
            }
            let _ = child.kill();
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SegmentationAudioClip {
    pub path: String,
    pub start_ms: i64,
    pub end_ms: i64,
    #[serde(default)]
    pub source_start_ms: i64,
}

/// Executes local WordTiming segmentation directly, identical to QuranCaption's
/// `segment_quran_audio_local_word_timing` command.
pub async fn execute_word_timing_segmentation(
    app_handle: AppHandle,
    audio_path: Option<String>,
    audio_clips: Option<Vec<SegmentationAudioClip>>,
    min_silence_ms: Option<u32>,
    min_speech_ms: Option<u32>,
    pad_ms: Option<u32>,
    qiraat: Option<String>,
) -> Result<serde_json::Value, String> {
    let mut python_exe_str = STATE.python_exe.lock().unwrap().clone();
    if python_exe_str.is_empty() {
        if let Ok(venv_dir) = get_engine_venv_path(&app_handle) {
            let venv_exe = get_venv_python_exe(&venv_dir);
            if venv_exe.exists() {
                python_exe_str = venv_exe.to_string_lossy().to_string();
                *STATE.python_exe.lock().unwrap() = python_exe_str.clone();
            }
        }
        if python_exe_str.is_empty() {
            if let Some(sys_exe) = resolve_system_python() {
                python_exe_str = sys_exe.to_string_lossy().to_string();
                *STATE.python_exe.lock().unwrap() = python_exe_str.clone();
            }
        }
    }
    if python_exe_str.is_empty() {
        return Err("Python environment not ready.".to_string());
    }
    let python_exe = PathBuf::from(&python_exe_str);
    let project_root = resolve_project_root(&app_handle)?;
    let script_py = {
        let candidates = [
            app_handle.path().resolve("python/local_word_timing_segmenter.py", tauri::path::BaseDirectory::Resource).unwrap_or_default(),
            app_handle.path().resolve("python/align_bridge.py", tauri::path::BaseDirectory::Resource).unwrap_or_default(),
            project_root.join("app").join("src-tauri").join("python").join("local_word_timing_segmenter.py"),
            project_root.join("app").join("src-tauri").join("python").join("align_bridge.py"),
            project_root.join("src-tauri").join("python").join("local_word_timing_segmenter.py"),
        ];
        candidates.into_iter().find(|p| p.is_file()).ok_or_else(|| {
            format!("Could not locate local_word_timing_segmenter.py in project: {}", project_root.display())
        })?
    };

    let target_audio = if let Some(clips) = audio_clips.as_ref().filter(|c| !c.is_empty()) {
        clips[0].path.clone()
    } else if let Some(path) = audio_path.as_ref() {
        path.clone()
    } else {
        return Err("Audio file not found: missing audio_path/audio_clips".to_string());
    };

    let mut cmd_args: Vec<String> = vec![
        script_py.to_string_lossy().to_string(),
        target_audio,
        "--fast".to_string(),
    ];
    if let Some(clips) = audio_clips.as_ref().filter(|c| !c.is_empty()) {
        cmd_args.push("--timeline-clips-json".to_string());
        cmd_args.push(serde_json::to_string(clips).map_err(|e| e.to_string())?);
    }
    if let Some(ms) = min_silence_ms {
        cmd_args.push("--min-silence-ms".to_string());
        cmd_args.push(ms.to_string());
    }
    if let Some(ms) = min_speech_ms {
        cmd_args.push("--min-speech-ms".to_string());
        cmd_args.push(ms.to_string());
    }
    if let Some(ms) = pad_ms {
        cmd_args.push("--pad-ms".to_string());
        cmd_args.push(ms.to_string());
    }
    if let Some(ref q) = qiraat {
        let q_trimmed = q.trim();
        if !q_trimmed.is_empty() {
            cmd_args.push("--qiraat".to_string());
            cmd_args.push(q_trimmed.to_lowercase());
        }
    }

    let mut cmd = Command::new(&python_exe);
    cmd.args(&cmd_args);
    cmd.current_dir(&project_root);
    cmd.env("PYTHONUNBUFFERED", "1");
    cmd.env("PYTHONIOENCODING", "utf-8");
    cmd.env("PYTHONUTF8", "1");
    cmd.env("PYTHONFAULTHANDLER", "1");
    cmd.env("QURAN_PROJECT_ROOT", project_root.to_string_lossy().as_ref());
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::piped());
    configure_command_no_window(&mut cmd);

    let mut child = cmd.spawn().map_err(|e| format!("Failed to execute Python segmenter: {}", e))?;
    let stdout_stream = child.stdout.take().ok_or("Failed to capture stdout from segmenter")?;
    let stderr_stream = child.stderr.take().ok_or("Failed to capture stderr from segmenter")?;

    // Store child for cancellation support via stop_engine() / stop_align()
    *STATE.child.lock().unwrap() = Some(child);

    let app_clone_stderr = app_handle.clone();
    let stderr_lines = Arc::new(Mutex::new(Vec::<String>::new()));
    let stderr_lines_clone = Arc::clone(&stderr_lines);

    let stderr_handle = std::thread::spawn(move || {
        let reader = BufReader::new(stderr_stream);
        for line in reader.lines() {
            if let Ok(line) = line {
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }
                if trimmed.starts_with("STATUS:") {
                    let json_str = trimmed.trim_start_matches("STATUS:");
                    if let Ok(status_data) = serde_json::from_str::<serde_json::Value>(json_str) {
                        let _ = app_clone_stderr.emit("segmentation-status", &status_data);
                        let _ = app_clone_stderr.emit(
                            "align-event",
                            serde_json::json!({ "type": "progress", "data": status_data }),
                        );
                    }
                } else {
                    let _ = app_clone_stderr.emit(
                        "align-event",
                        serde_json::json!({ "type": "stderr", "text": trimmed }),
                    );
                    if let Ok(mut l) = stderr_lines_clone.lock() {
                        l.push(trimmed.to_string());
                        if l.len() > 120 {
                            let drain = l.len() - 120;
                            l.drain(0..drain);
                        }
                    }
                }
            }
        }
    });

    let mut stdout_buffer = String::new();
    let reader = BufReader::new(stdout_stream);
    for line in reader.lines() {
        let Ok(line) = line else { break };
        stdout_buffer.push_str(&line);
        stdout_buffer.push('\n');
    }

    let exit_code = {
        let mut lock = STATE.child.lock().unwrap();
        if let Some(ref mut child) = *lock {
            child.wait().map(|s| s.code().unwrap_or(-1)).unwrap_or(-1)
        } else {
            -1
        }
    };
    *STATE.child.lock().unwrap() = None;
    let _ = stderr_handle.join();

    if exit_code == 0 {
        let result = extract_json_payload(&stdout_buffer)
            .map_err(|e| {
                let stderr_text = stderr_lines.lock().map(|l| l.join("\n")).unwrap_or_default();
                if stderr_text.trim().is_empty() {
                    format!("Failed to parse Python JSON output: {}", e)
                } else {
                    format!("Failed to parse Python JSON output: {} (stderr: {})", e, stderr_text.trim())
                }
            })?;
        if let Some(error) = result.get("error").and_then(|e| e.as_str()) {
            return Err(error.to_string());
        }
        Ok(result)
    } else {
        let stderr_text = stderr_lines.lock().map(|l| l.join("\n")).unwrap_or_default();
        Err(format!("Python segmenter failed with code {}. {}", exit_code, stderr_text.trim()))
    }
}

