use std::fs;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use lazy_static::lazy_static;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};

use crate::process_utils::{configure_command_no_window, sanitize_cmd_error};

pub const MIN_PYTHON_MAJOR: u8 = 3;
pub const MIN_PYTHON_MINOR: u8 = 10;
pub const MAX_PYTHON_MINOR: u8 = 14;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EngineStatus {
    pub ready: bool,
    pub port: u16,
    pub python: String,
    pub message: String,
}

struct EngineGlobalState {
    child: Mutex<Option<Child>>,
    port: Mutex<u16>,
    ready: AtomicBool,
    progress: Mutex<u8>,
    python_exe: Mutex<String>,
    status_message: Mutex<String>,
}

lazy_static! {
    static ref STATE: EngineGlobalState = EngineGlobalState {
        child: Mutex::new(None),
        port: Mutex::new(8000),
        ready: AtomicBool::new(false),
        progress: Mutex::new(0),
        python_exe: Mutex::new(String::new()),
        status_message: Mutex::new("Engine uninitialized".to_string()),
    };
}

pub fn get_engine_status() -> EngineStatus {
    EngineStatus {
        ready: STATE.ready.load(Ordering::Relaxed),
        port: *STATE.port.lock().unwrap(),
        python: STATE.python_exe.lock().unwrap().clone(),
        message: STATE.status_message.lock().unwrap().clone(),
    }
}

pub fn set_status_progress(app: Option<&AppHandle>, msg: &str, progress: u8, ready: bool) {
    if let Ok(mut m) = STATE.status_message.lock() {
        *m = msg.to_string();
    }
    STATE.ready.store(ready, Ordering::Relaxed);
    
    // Monotonic guarantee: progress only moves forward and never jumps backward to 0 or 10
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
        let port = *STATE.port.lock().unwrap();
        let _ = handle.emit(
            "engine-status",
            serde_json::json!({
                "ready": ready,
                "port": port,
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

/// Reads the major, minor, patch version of a Python executable.
pub fn read_python_version(python_exe: &Path) -> Option<(u8, u8, u8)> {
    let check_script =
        "import json,sys; print(json.dumps({'major':sys.version_info[0],'minor':sys.version_info[1],'patch':sys.version_info[2]}))";
    let mut cmd = Command::new(python_exe);
    cmd.args(["-c", check_script]);
    configure_command_no_window(&mut cmd);
    let output = cmd.output().ok()?;
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

/// Probes for a compatible system Python in PATH (supports 3.10 to 3.14).
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
        let mut cmd = Command::new(candidate);
        cmd.args(["-c", "import sys; print(sys.executable)"]);
        configure_command_no_window(&mut cmd);
        if let Ok(output) = cmd.output() {
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
    // Check root directly as fallback
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

/// Standalone portable Python 3.14 with pre-packaged pip & venv (python-build-standalone).
pub fn get_portable_python_download_info() -> Result<(&'static str, &'static str), String> {
    if cfg!(target_os = "windows") {
        Ok((
            "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.14.8%2B20261003-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
            "cpython-3.14-windows-x64.tar.gz",
        ))
    } else if cfg!(target_os = "macos") {
        if cfg!(target_arch = "aarch64") {
            Ok((
                "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.14.8%2B20261003-aarch64-apple-darwin-install_only_stripped.tar.gz",
                "cpython-3.14-macos-arm64.tar.gz",
            ))
        } else {
            Ok((
                "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.14.8%2B20261003-x86_64-apple-darwin-install_only_stripped.tar.gz",
                "cpython-3.14-macos-x64.tar.gz",
            ))
        }
    } else if cfg!(target_os = "linux") {
        Ok((
            "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.14.8%2B20261003-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
            "cpython-3.14-linux-x64.tar.gz",
        ))
    } else {
        Err("Unsupported operating system for portable Python.".to_string())
    }
}

/// Downloads a binary file with progress callbacks (exact QuranCaption pattern).
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

/// Extracts standalone portable Python 3.14 (pip pre-packaged, no get-pip.py or ._pth hack required).
pub async fn ensure_portable_python_runtime(app_handle: &AppHandle) -> Result<PathBuf, String> {
    let portable_root = get_portable_python_root(app_handle)?;
    let portable_exe = get_portable_python_exe(app_handle)?;
    if portable_exe.exists() {
        if let Some((major, minor, _)) = read_python_version(&portable_exe) {
            if python_version_meets_min(major, minor) {
                // Ensure pip is available inside the standalone installation
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
            (p, format!("Downloading Python 3.14 standalone ({:.1}/{:.1} MB)...", mb_down, mb_tot))
        } else {
            let mb_down = downloaded as f64 / 1_048_576.0;
            (10, format!("Downloading Python 3.14 standalone ({:.1} MB)...", mb_down))
        };
        set_status_progress(Some(app_handle), &status_text, pct, false);
    })
    .await?;

    set_status_progress(Some(app_handle), "Extracting Python 3.14 standalone runtime...", 22, false);

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

    set_status_progress(Some(app_handle), "Python 3.14 standalone runtime ready.", 25, false);
    Ok(portable_exe)
}

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

/// Creates a dedicated, isolated venv (exact QuranCaption pattern).
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
    cmd.args(["-m", "venv", venv_dir.to_string_lossy().as_ref()]);
    configure_command_no_window(&mut cmd);

    let output = cmd.output().map_err(|e| format!("Failed to run venv: {}", e))?;
    if !output.status.success() {
        // Fallback to virtualenv (works on Windows embedded Python)
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

/// Executes pip install in streaming mode with real-time UI progress (exact QuranCaption pattern).
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
            let pct = (start_pct as f32 + (step_count as f32 * 1.8).min(span - 2.0)) as u8;
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
            let pct = (start_pct as f32 + (step_count as f32 * 1.8).min(span - 2.0)) as u8;
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

/// Ensures dependencies are installed in the venv using real-time streaming feedback.
pub fn ensure_dependencies(app_handle: &AppHandle, python_exe: &Path) -> Result<(), String> {
    let check_script = r#"
import sys
for mod in ["fastapi", "uvicorn", "numpy", "onnxruntime"]:
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
        "fastapi",
        "uvicorn",
        "python-multipart",
        "pydantic",
        "requests",
        "numpy",
        "onnxruntime",
        "numba",
        "miniaudio",
        "scipy",
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

/// Locates the root directory containing the `engine` and `src` python packages.
pub fn resolve_project_root(app_handle: &AppHandle) -> Result<PathBuf, String> {
    // 1. Try bundled resources
    if let Ok(res_dir) = app_handle.path().resource_dir() {
        if res_dir.join("engine").join("server.py").exists() || res_dir.join("run.py").exists() {
            return Ok(res_dir);
        }
    }

    // 2. Try development path relative to executable
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            let candidate1 = exe_dir.join("..").join("..");
            if candidate1.join("app").join("engine").join("server.py").exists() {
                return Ok(candidate1);
            }
            if candidate1.join("engine").join("server.py").exists() {
                return Ok(candidate1);
            }
            let candidate2 = exe_dir.join("..").join("..").join("..");
            if candidate2.join("app").join("engine").join("server.py").exists() {
                return Ok(candidate2);
            }
        }
    }

    // 3. Fallback to current working directory
    if let Ok(cwd) = std::env::current_dir() {
        if cwd.join("app").join("engine").join("server.py").exists() {
            return Ok(cwd);
        }
        if cwd.join("engine").join("server.py").exists() {
            return Ok(cwd);
        }
    }

    Err("Could not locate Quran Recite Studio engine files".to_string())
}

/// Checks if the engine server is already running and responding.
async fn is_engine_alive(port: u16) -> bool {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_millis(600))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    let url = format!("http://127.0.0.1:{}/api/status", port);
    match client.get(&url).send().await {
        Ok(res) => res.status().is_success(),
        Err(_) => false,
    }
}

pub fn is_port_available(port: u16) -> bool {
    std::net::TcpListener::bind(("127.0.0.1", port)).is_ok()
}

pub fn find_free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(8000)
}

pub fn get_engine_port() -> u16 {
    *STATE.port.lock().unwrap()
}

/// Ensures Silero VAD and Zipformer Arabic Acoustic ONNX models are present on disk (exact QuranCaption pattern).
pub async fn ensure_engine_models(app_handle: &AppHandle) -> Result<(), String> {
    let project_root = resolve_project_root(app_handle)?;
    let onnx_dir = project_root.join("data").join("onnx");
    fs::create_dir_all(&onnx_dir).map_err(|e| format!("Failed to create onnx dir: {}", e))?;

    // 1. Silero VAD model (~1.3 MB)
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

    // 2. Zipformer Arabic acoustic model (~72 MB)
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

/// Returns true if Python venv, core packages, and ONNX models are already downloaded & present.
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

/// Starts the FastAPI background engine and waits for readiness.
pub async fn start_engine(app_handle: AppHandle) -> Result<(), String> {
    let mut port = *STATE.port.lock().unwrap();
    if is_engine_alive(port).await {
        set_status_progress(Some(&app_handle), "Python Alignment Engine Connected", 100, true);
        return Ok(());
    }

    // Prefer standard port 8000 if free; otherwise find an ephemeral free port
    if is_port_available(8000) {
        port = 8000;
    } else {
        port = find_free_port();
    }
    *STATE.port.lock().unwrap() = port;

    let already_installed = is_environment_fully_installed(&app_handle);

    // Only emit setup progress to UI if files are actually missing (first run)
    if !already_installed {
        set_status_progress(Some(&app_handle), "Resolving Python environment...", 5, false);
    }

    // 1. Resolve base Python: check system python first, then auto-provision portable python
    let base_python = match resolve_system_python() {
        Some(sys) => sys,
        None => {
            ensure_portable_python_runtime(&app_handle).await?
        }
    };

    // 2. Create isolated venv from base Python (exact QuranCaption pattern)
    let venv_dir = create_venv_if_missing(&app_handle, &base_python)?;
    let venv_python_exe = get_venv_python_exe(&venv_dir);
    *STATE.python_exe.lock().unwrap() = venv_python_exe.to_string_lossy().to_string();

    // 3. Stream pip install into the venv with live UI progress
    ensure_dependencies(&app_handle, &venv_python_exe)?;

    let project_root = resolve_project_root(&app_handle)?;

    // Preload and deploy bundled MSVC DLLs into onnxruntime/capi immediately (exact QuranCaption pattern)
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

    // 4. Ensure AI Models are downloaded with streaming progress
    ensure_engine_models(&app_handle).await?;

    // 5. Resolve server script
    let server_script = if project_root.join("engine").join("server.py").exists() {
        project_root.join("engine").join("server.py")
    } else {
        project_root.join("app").join("engine").join("server.py")
    };

    if !already_installed {
        set_status_progress(Some(&app_handle), "Starting Alignment Server...", 96, false);
    }
    let mut cmd = Command::new(&venv_python_exe);
    cmd.arg(server_script);
    cmd.current_dir(&project_root);
    cmd.env("PORT", port.to_string());
    cmd.env("PYTHONUNBUFFERED", "1");
    cmd.env("QURAN_PROJECT_ROOT", project_root.to_string_lossy().to_string());

    // Add bundled binaries and data/bin to PATH so ffmpeg, ffprobe, and MSVC runtime DLLs are always available
    let path_var = std::env::var("PATH").unwrap_or_default();
    let sep = if cfg!(target_os = "windows") { ";" } else { ":" };
    let mut extra_paths = Vec::new();

    if let Ok(res_dir) = app_handle.path().resource_dir() {
        let bin_dir = res_dir.join("binaries");
        if bin_dir.exists() {
            extra_paths.push(bin_dir.to_string_lossy().to_string());
        }
    }
    let data_bin_dir = project_root.join("data").join("bin");
    if data_bin_dir.exists() {
        extra_paths.push(data_bin_dir.to_string_lossy().to_string());
    }
    if !extra_paths.is_empty() {
        cmd.env("PATH", format!("{}{}{}", extra_paths.join(sep), sep, path_var));
    }

    configure_command_no_window(&mut cmd);

    let child = cmd.spawn().map_err(|e| format!("Failed to spawn engine server: {}", e))?;
    *STATE.child.lock().unwrap() = Some(child);

    // Wait for health endpoint on the chosen dynamic port
    for step in 0..60 {
        tokio::time::sleep(Duration::from_millis(250)).await;
        if is_engine_alive(port).await {
            set_status_progress(Some(&app_handle), "Python Alignment Engine Ready", 100, true);
            return Ok(());
        }
        let p_wait = 90 + ((step as f32 / 60.0) * 8.0).round() as u8;
        set_status_progress(Some(&app_handle), "Waiting for Alignment Engine...", p_wait, false);
    }

    Err(format!(
        "Timeout waiting for Python Alignment Engine to start on port {}",
        port
    ))
}

/// Terminates the background engine child process cleanly.
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
