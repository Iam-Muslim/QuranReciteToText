use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use lazy_static::lazy_static;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::AsyncWriteExt;

use crate::process_utils::configure_command_no_window;

pub const MIN_PYTHON_MAJOR: u8 = 3;
pub const MIN_PYTHON_MINOR: u8 = 10;
pub const MAX_PYTHON_MINOR: u8 = 13;

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
    python_exe: Mutex<String>,
    status_message: Mutex<String>,
}

lazy_static! {
    static ref STATE: EngineGlobalState = EngineGlobalState {
        child: Mutex::new(None),
        port: Mutex::new(8000),
        ready: AtomicBool::new(false),
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
    if let Some(handle) = app {
        let _ = handle.emit(
            "engine-status",
            serde_json::json!({
                "ready": ready,
                "port": *STATE.port.lock().unwrap(),
                "message": msg,
                "progress": progress
            }),
        );
        let _ = handle.emit(
            "install-status",
            serde_json::json!({
                "message": msg,
                "progress": progress,
                "ready": ready
            }),
        );
    }
}

pub fn set_status(app: Option<&AppHandle>, msg: &str, ready: bool) {
    let p = if ready { 100 } else { 10 };
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

/// Probes for a compatible system Python in PATH.
pub fn resolve_system_python() -> Option<PathBuf> {
    let candidates = if cfg!(target_os = "windows") {
        vec!["python3.12", "python3.11", "python3.10", "python", "python3"]
    } else if cfg!(target_os = "macos") {
        vec![
            "/opt/homebrew/bin/python3.12",
            "/opt/homebrew/bin/python3.11",
            "/opt/homebrew/bin/python3.10",
            "/usr/local/bin/python3.12",
            "/usr/local/bin/python3.11",
            "/usr/local/bin/python3.10",
            "python3.12",
            "python3.11",
            "python3.10",
            "python3",
            "python",
        ]
    } else {
        vec!["python3.12", "python3.11", "python3.10", "python3", "python"]
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
    if cfg!(target_os = "windows") {
        Ok(root.join("python").join("python.exe"))
    } else {
        Ok(root.join("python").join("bin").join("python3"))
    }
}

pub fn get_portable_python_download_info() -> Result<(&'static str, &'static str), String> {
    if cfg!(target_os = "windows") {
        Ok((
            "https://www.python.org/ftp/python/3.11.0/python-3.11.0-embed-amd64.zip",
            "python-3.11.0-embed-amd64.zip",
        ))
    } else if cfg!(target_os = "macos") {
        if cfg!(target_arch = "aarch64") {
            Ok((
                "https://github.com/astral-sh/python-build-standalone/releases/download/20261001/cpython-3.11.17%2B20261001-aarch64-apple-darwin-install_only_stripped.tar.gz",
                "cpython-3.11-macos-arm64.tar.gz",
            ))
        } else {
            Ok((
                "https://github.com/astral-sh/python-build-standalone/releases/download/20261001/cpython-3.11.17%2B20261001-x86_64-apple-darwin-install_only_stripped.tar.gz",
                "cpython-3.11-macos-x64.tar.gz",
            ))
        }
    } else if cfg!(target_os = "linux") {
        Ok((
            "https://github.com/astral-sh/python-build-standalone/releases/download/20261001/cpython-3.11.17%2B20261001-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
            "cpython-3.11-linux-x64.tar.gz",
        ))
    } else {
        Err("Unsupported operating system for portable Python.".to_string())
    }
}

async fn download_file_with_progress(
    app_handle: Option<&AppHandle>,
    url: &str,
    destination: &Path,
    label: &str,
    base_progress: u8,
    scale_progress: u8,
) -> Result<(), String> {
    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())?;

    let response = client
        .get(url)
        .send()
        .await
        .map_err(|e| format!("Failed to download {}: {}", url, e))?;

    if !response.status().is_success() {
        return Err(format!("Download failed with status: {}", response.status()));
    }

    let total = response.content_length();
    let temp_path = destination.with_extension("download");
    let mut file = tokio::fs::File::create(&temp_path)
        .await
        .map_err(|e| e.to_string())?;

    let mut stream = response;
    let mut downloaded = 0u64;
    let mut last_emit = std::time::Instant::now();

    while let Some(chunk) = stream.chunk().await.map_err(|e| e.to_string())? {
        file.write_all(&chunk).await.map_err(|e| e.to_string())?;
        downloaded += chunk.len() as u64;

        if last_emit.elapsed() >= Duration::from_millis(150) {
            if let Some(tot) = total {
                let ratio = (downloaded as f32 / tot as f32).min(1.0);
                let p = base_progress + (ratio * (scale_progress as f32)).round() as u8;
                let mb_down = downloaded as f64 / 1_048_576.0;
                let mb_tot = tot as f64 / 1_048_576.0;
                set_status_progress(
                    app_handle,
                    &format!("{} ({:.1}/{:.1} MB)", label, mb_down, mb_tot),
                    p,
                    false,
                );
            }
            last_emit = std::time::Instant::now();
        }
    }
    file.flush().await.map_err(|e| e.to_string())?;
    drop(file);

    tokio::fs::rename(&temp_path, destination)
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

async fn download_file(url: &str, destination: &Path) -> Result<(), String> {
    download_file_with_progress(None, url, destination, "Downloading", 0, 100).await
}

/// Ensures a valid portable Python 3.11 is present on fresh devices.
pub async fn ensure_portable_python(app_handle: &AppHandle) -> Result<PathBuf, String> {
    let portable_exe = get_portable_python_exe(app_handle)?;
    if portable_exe.exists() {
        if read_python_version(&portable_exe).is_some() {
            return Ok(portable_exe);
        }
        let root = get_portable_python_root(app_handle)?;
        let _ = fs::remove_dir_all(root.join("python"));
    }

    let root = get_portable_python_root(app_handle)?;
    fs::create_dir_all(&root).map_err(|e| e.to_string())?;

    let (url, filename) = get_portable_python_download_info()?;
    let archive_path = root.join(filename);

    download_file_with_progress(
        Some(app_handle),
        url,
        &archive_path,
        "Downloading Python 3.11 runtime",
        5,
        20,
    )
    .await?;

    set_status_progress(Some(app_handle), "Extracting Python 3.11 runtime...", 28, false);
    let python_dir = root.join("python");
    fs::create_dir_all(&python_dir).map_err(|e| e.to_string())?;

    let tar_bin = if cfg!(target_os = "windows") {
        let sys_tar = Path::new("C:\\Windows\\System32\\tar.exe");
        if sys_tar.exists() {
            sys_tar.to_string_lossy().to_string()
        } else {
            "tar".to_string()
        }
    } else {
        "tar".to_string()
    };

    let mut cmd = Command::new(&tar_bin);
    if cfg!(target_os = "windows") {
        cmd.args([
            "-xf",
            archive_path.to_str().unwrap(),
            "-C",
            python_dir.to_str().unwrap(),
        ]);
    } else {
        cmd.args([
            "-xzf",
            archive_path.to_str().unwrap(),
            "-C",
            root.to_str().unwrap(),
        ]);
    }
    configure_command_no_window(&mut cmd);
    let output = cmd.output().map_err(|e| format!("Failed to extract Python: {}", e))?;
    let _ = fs::remove_file(&archive_path);

    if !output.status.success() {
        return Err(format!(
            "Failed to extract Python archive: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    if cfg!(target_os = "windows") {
        // Configure python311._pth to import site and Lib/site-packages
        let pth_file = python_dir.join("python311._pth");
        if pth_file.exists() {
            if let Ok(content) = fs::read_to_string(&pth_file) {
                let mut lines: Vec<String> = content
                    .lines()
                    .map(|l| {
                        let t = l.trim();
                        if t == "#import site" || t == "# import site" {
                            "import site".to_string()
                        } else {
                            l.to_string()
                        }
                    })
                    .collect();
                if !lines.iter().any(|l| l.trim() == "import site") {
                    lines.push("import site".to_string());
                }
                if !lines.iter().any(|l| l.trim() == "Lib/site-packages" || l.trim() == "Lib\\site-packages") {
                    lines.push("Lib/site-packages".to_string());
                }
                let _ = fs::write(&pth_file, lines.join("\n"));
            }
        }
        let _ = fs::create_dir_all(python_dir.join("Lib").join("site-packages"));

        // Bootstrap pip
        set_status(Some(app_handle), "Bootstrapping pip package manager...", false);
        let get_pip_path = python_dir.join("get-pip.py");
        download_file("https://bootstrap.pypa.io/get-pip.py", &get_pip_path).await?;

        let mut pip_boot = Command::new(&portable_exe);
        pip_boot.args([
            get_pip_path.to_str().unwrap(),
            "--no-warn-script-location",
            "--quiet",
        ]);
        configure_command_no_window(&mut pip_boot);
        let _ = pip_boot.output();
        let _ = fs::remove_file(&get_pip_path);
    }

    if !portable_exe.exists() || read_python_version(&portable_exe).is_none() {
        return Err(format!(
            "Portable Python installed but binary invalid at {}",
            portable_exe.to_string_lossy()
        ));
    }

    Ok(portable_exe)
}

/// Resolves Python interpreter: prefers portable if already setup, falls back to system, then downloads portable.
pub async fn resolve_or_provision_python(app_handle: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(portable) = get_portable_python_exe(app_handle) {
        if portable.exists() && read_python_version(&portable).is_some() {
            return Ok(portable);
        }
    }

    if let Some(sys_py) = resolve_system_python() {
        return Ok(sys_py);
    }

    ensure_portable_python(app_handle).await
}

/// Checks and installs required Python packages if missing.
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

    set_status(Some(app_handle), "Installing essential Python dependencies...", false);
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

    let mut pip_cmd = Command::new(python_exe);
    pip_cmd.args(["-m", "pip", "install", "--no-warn-script-location", "--disable-pip-version-check"]);
    pip_cmd.args(packages);
    configure_command_no_window(&mut pip_cmd);
    let pip_out = pip_cmd.output().map_err(|e| format!("Pip install failed: {}", e))?;
    if !pip_out.status.success() {
        return Err(format!(
            "Failed to install Python dependencies: {}",
            String::from_utf8_lossy(&pip_out.stderr)
        ));
    }
    Ok(())
}

/// Locates the root directory containing the `engine` and `src` python packages.
pub fn resolve_project_root(app_handle: &AppHandle) -> Result<PathBuf, String> {
    // 1. Try bundled resources
    if let Ok(res_dir) = app_handle.path().resource_dir() {
        if res_dir.join("engine").join("server.py").exists() {
            return Ok(res_dir);
        }
    }

    // 2. Try development path relative to executable
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            // Check workspace root: target/release/../../
            let candidate1 = exe_dir.join("..").join("..");
            if candidate1.join("app").join("engine").join("server.py").exists() {
                return Ok(candidate1);
            }
            if candidate1.join("engine").join("server.py").exists() {
                return Ok(candidate1);
            }
            // Check app/src-tauri/../../
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

/// Finds a guaranteed free TCP port assigned by the OS kernel (zero port collisions).
pub fn find_free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(8000)
}

pub fn get_engine_port() -> u16 {
    *STATE.port.lock().unwrap()
}

/// Starts the FastAPI background engine and waits for readiness.
pub async fn start_engine(app_handle: AppHandle) -> Result<(), String> {
    let mut port = *STATE.port.lock().unwrap();
    if is_engine_alive(port).await {
        set_status(Some(&app_handle), "Python Alignment Engine Connected", true);
        return Ok(());
    }

    // Choose an available port from the OS
    port = find_free_port();
    *STATE.port.lock().unwrap() = port;

    set_status(Some(&app_handle), "Initializing Python environment...", false);
    let python_exe = resolve_or_provision_python(&app_handle).await?;
    *STATE.python_exe.lock().unwrap() = python_exe.to_string_lossy().to_string();

    ensure_dependencies(&app_handle, &python_exe)?;

    let project_root = resolve_project_root(&app_handle)?;
    let server_script = if project_root.join("engine").join("server.py").exists() {
        project_root.join("engine").join("server.py")
    } else {
        project_root.join("app").join("engine").join("server.py")
    };

    set_status(Some(&app_handle), "Starting Alignment Server...", false);
    let mut cmd = Command::new(&python_exe);
    cmd.arg(server_script);
    cmd.current_dir(&project_root);
    cmd.env("PORT", port.to_string());
    cmd.env("PYTHONUNBUFFERED", "1");

    // Add bundled binaries to PATH so ffmpeg and ffprobe are always available
    if let Ok(res_dir) = app_handle.path().resource_dir() {
        let bin_dir = res_dir.join("binaries");
        if bin_dir.exists() {
            let path_var = std::env::var("PATH").unwrap_or_default();
            let sep = if cfg!(target_os = "windows") { ";" } else { ":" };
            cmd.env("PATH", format!("{}{}{}", bin_dir.to_string_lossy(), sep, path_var));
        }
    }

    configure_command_no_window(&mut cmd);

    let child = cmd.spawn().map_err(|e| format!("Failed to spawn engine server: {}", e))?;
    *STATE.child.lock().unwrap() = Some(child);

    // Wait for health endpoint on the chosen dynamic port
    for _ in 0..60 {
        tokio::time::sleep(Duration::from_millis(250)).await;
        if is_engine_alive(port).await {
            set_status(Some(&app_handle), "Python Alignment Engine Ready", true);
            return Ok(());
        }
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
