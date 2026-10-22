mod process_utils;
mod engine_manager;
mod waveform;

use std::fs;
use std::path::{Path, PathBuf};
use tauri::{AppHandle, Manager};
use serde::Deserialize;

// ── Basic helpers ─────────────────────────────────────────────────────────────

#[tauri::command]
fn get_app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
fn get_engine_status() -> engine_manager::EngineStatus {
    engine_manager::get_engine_status()
}

#[tauri::command]
fn is_engine_installed(app_handle: AppHandle) -> bool {
    engine_manager::is_environment_fully_installed(&app_handle)
}

#[tauri::command]
async fn ensure_engine(app_handle: AppHandle) -> Result<engine_manager::EngineStatus, String> {
    // Repair/verification flow: always run the full engine audit.
    engine_manager::start_engine(app_handle.clone(), true).await?;
    Ok(engine_manager::get_engine_status())
}

// ── Alignment — direct process execution ──────────────────────────────────────

#[derive(Debug, Deserialize)]
struct AlignRequest {
    audio_path: Option<String>,
    dir_path: Option<String>,
    fast: Option<bool>,
    qiraat: Option<String>,
}

/// Starts alignment by spawning the Python segmenter directly.
/// Progress is streamed via the `align-event` Tauri event, NOT HTTP.
/// Runs on a blocking worker thread so the UI never freezes while the
/// engine is being stopped/started.
#[tauri::command]
async fn run_align(app_handle: AppHandle, request: AlignRequest) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        engine_manager::run_alignment(
            app_handle,
            request.audio_path,
            request.dir_path,
            request.fast.unwrap_or(false),
            request.qiraat,
        )
    })
    .await
    .map_err(|e| format!("Alignment task failed: {}", e))?
}

/// Direct execution matching QuranCaption command `segment_quran_audio_local_word_timing`.
#[tauri::command]
async fn segment_quran_audio_local_word_timing(
    app_handle: AppHandle,
    audio_path: Option<String>,
    audio_clips: Option<Vec<engine_manager::SegmentationAudioClip>>,
    min_silence_ms: Option<u32>,
    min_speech_ms: Option<u32>,
    pad_ms: Option<u32>,
    qiraat: Option<String>,
) -> Result<serde_json::Value, String> {
    engine_manager::execute_word_timing_segmentation(
        app_handle,
        audio_path,
        audio_clips,
        min_silence_ms,
        min_speech_ms,
        pad_ms,
        qiraat,
    )
    .await
}

/// Matches QuranCaption's `check_local_segmentation_ready` command.
#[tauri::command]
async fn check_local_segmentation_ready(
    app_handle: AppHandle,
    _hf_token: Option<String>,
) -> Result<serde_json::Value, String> {
    let installed = engine_manager::is_environment_fully_installed(&app_handle);
    let status = engine_manager::get_engine_status();
    Ok(serde_json::json!({
        "ready": status.ready || installed,
        "pythonInstalled": true,
        "packagesInstalled": installed,
        "message": if installed { "Local segmentation is ready" } else { "WordTiming offline engine needs installation" },
        "engines": {
            "quranwordtiming": {
                "ready": installed,
                "venvExists": installed,
                "packagesInstalled": installed,
                "usable": installed,
                "message": if installed { "WordTiming offline engine is ready" } else { "WordTiming offline engine not installed" }
            }
        }
    }))
}

/// Matches QuranCaption's `install_local_segmentation_deps` command.
#[tauri::command]
async fn install_local_segmentation_deps(
    app_handle: AppHandle,
    _engine: String,
    _hf_token: Option<String>,
) -> Result<String, String> {
    // Explicit install/repair request: force the full dependency audit.
    engine_manager::start_engine(app_handle, true).await?;
    Ok("Installation completed successfully".to_string())
}

/// Stops the active alignment process.
#[tauri::command]
fn stop_align() {
    engine_manager::stop_engine();
}

// ── Project management (direct disk, no HTTP) ─────────────────────────────────

fn get_projects_dir(app_handle: &AppHandle) -> Result<PathBuf, String> {
    let data_dir = app_handle
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?;
    Ok(data_dir.join("projects"))
}

/// Lists all .qproj files in the app data projects directory.
#[tauri::command]
fn list_projects(app_handle: AppHandle) -> Result<serde_json::Value, String> {
    let projects_dir = get_projects_dir(&app_handle)?;
    fs::create_dir_all(&projects_dir).map_err(|e| e.to_string())?;

    let mut projects: Vec<serde_json::Value> = Vec::new();
    for entry in fs::read_dir(&projects_dir).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        let path = entry.path();
        if path.extension().map(|e| e == "qproj").unwrap_or(false) {
            if let Ok(content) = fs::read_to_string(&path) {
                if let Ok(mut data) = serde_json::from_str::<serde_json::Value>(&content) {
                    // Inject filename for frontend reference
                    let fname = path.file_name().unwrap_or_default().to_string_lossy().to_string();
                    if let Some(obj) = data.as_object_mut() {
                        obj.insert("file_name".to_string(), serde_json::json!(fname.clone()));
                        obj.insert("_file".to_string(), serde_json::json!(fname.clone()));
                        obj.insert("_path".to_string(), serde_json::json!(path.to_string_lossy().to_string()));
                    }
                    projects.push(data);
                }
            }
        }
    }
    // Sort by modified time descending (most recent first)
    Ok(serde_json::json!({ "projects": projects }))
}

/// Loads a project by filename.
#[tauri::command]
fn load_project(app_handle: AppHandle, file: String) -> Result<serde_json::Value, String> {
    let projects_dir = get_projects_dir(&app_handle)?;
    let safe_name = sanitize_filename(&file);
    let path = projects_dir.join(&safe_name);
    if !path.exists() {
        // Also try exact file name in case sanitize differed
        let direct_path = projects_dir.join(&file);
        if direct_path.exists() {
            let content = fs::read_to_string(&direct_path).map_err(|e| e.to_string())?;
            let mut data: serde_json::Value = serde_json::from_str(&content).map_err(|e| e.to_string())?;
            if let Some(obj) = data.as_object_mut() {
                obj.entry("file_name".to_string()).or_insert_with(|| serde_json::json!(file.clone()));
                obj.entry("_file".to_string()).or_insert_with(|| serde_json::json!(file.clone()));
                obj.entry("_path".to_string()).or_insert_with(|| serde_json::json!(direct_path.to_string_lossy().to_string()));
            }
            return Ok(data);
        }
        return Err(format!("Project file not found: {}", file));
    }
    let content = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut data: serde_json::Value = serde_json::from_str(&content).map_err(|e| e.to_string())?;
    if let Some(obj) = data.as_object_mut() {
        obj.entry("file_name".to_string()).or_insert_with(|| serde_json::json!(safe_name.clone()));
        obj.entry("_file".to_string()).or_insert_with(|| serde_json::json!(safe_name.clone()));
        obj.entry("_path".to_string()).or_insert_with(|| serde_json::json!(path.to_string_lossy().to_string()));
    }
    Ok(data)
}

#[derive(Debug, Deserialize)]
struct SaveProjectRequest {
    file: String,
    data: serde_json::Value,
}

/// Saves a project atomically (write to .part, then rename).
#[tauri::command]
fn save_project(app_handle: AppHandle, request: SaveProjectRequest) -> Result<(), String> {
    let projects_dir = get_projects_dir(&app_handle)?;
    fs::create_dir_all(&projects_dir).map_err(|e| e.to_string())?;

    let safe_name = sanitize_filename(&request.file);
    let dest = projects_dir.join(&safe_name);
    let temp = dest.with_extension("part");

    let mut data = request.data;
    if let Some(obj) = data.as_object_mut() {
        obj.insert("file_name".to_string(), serde_json::json!(safe_name.clone()));
        obj.insert("_file".to_string(), serde_json::json!(safe_name.clone()));
        obj.insert("_path".to_string(), serde_json::json!(dest.to_string_lossy().to_string()));
    }

    let json_str = serde_json::to_string_pretty(&data).map_err(|e| e.to_string())?;
    fs::write(&temp, json_str).map_err(|e| format!("Failed to write project: {}", e))?;
    fs::rename(&temp, &dest).map_err(|e| format!("Failed to save project: {}", e))?;
    Ok(())
}

#[derive(Debug, Deserialize)]
struct CreateProjectRequest {
    name: String,
    data: serde_json::Value,
}

/// Creates a new project file.
#[tauri::command]
fn create_project(app_handle: AppHandle, request: CreateProjectRequest) -> Result<serde_json::Value, String> {
    let projects_dir = get_projects_dir(&app_handle)?;
    fs::create_dir_all(&projects_dir).map_err(|e| e.to_string())?;

    let safe_name = sanitize_filename(&format!("{}.qproj", request.name));
    let dest = unique_path(&projects_dir, &safe_name);

    let fname = dest.file_name().unwrap_or_default().to_string_lossy().to_string();
    let mut data = request.data;
    if let Some(obj) = data.as_object_mut() {
        obj.insert("file_name".to_string(), serde_json::json!(fname.clone()));
        obj.insert("_file".to_string(), serde_json::json!(fname.clone()));
        obj.insert("_path".to_string(), serde_json::json!(dest.to_string_lossy().to_string()));
    }

    let json_str = serde_json::to_string_pretty(&data).map_err(|e| e.to_string())?;
    fs::write(&dest, json_str).map_err(|e| e.to_string())?;

    Ok(serde_json::json!({ "file": fname.clone(), "file_name": fname, "path": dest.to_string_lossy() }))
}

#[derive(Debug, Deserialize)]
struct DeleteProjectRequest {
    file: String,
}

/// Deletes a project file.
#[tauri::command]
fn delete_project(app_handle: AppHandle, request: DeleteProjectRequest) -> Result<(), String> {
    let projects_dir = get_projects_dir(&app_handle)?;
    let safe_name = sanitize_filename(&request.file);
    let path = projects_dir.join(&safe_name);
    if path.exists() {
        fs::remove_file(&path).map_err(|e| e.to_string())?;
    } else {
        let direct_path = projects_dir.join(&request.file);
        if direct_path.exists() {
            fs::remove_file(&direct_path).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

#[derive(Debug, Deserialize)]
struct DuplicateProjectRequest {
    file: String,
}

/// Duplicates a project file.
#[tauri::command]
fn duplicate_project(app_handle: AppHandle, request: DuplicateProjectRequest) -> Result<serde_json::Value, String> {
    let projects_dir = get_projects_dir(&app_handle)?;
    let src = projects_dir.join(&request.file);
    if !src.exists() {
        return Err(format!("Project not found: {}", request.file));
    }
    let stem = src.file_stem().unwrap_or_default().to_string_lossy().to_string();
    let copy_name = format!("{} Copy.qproj", stem);
    let dest = unique_path(&projects_dir, &copy_name);
    fs::copy(&src, &dest).map_err(|e| e.to_string())?;
    let fname = dest.file_name().unwrap_or_default().to_string_lossy().to_string();
    Ok(serde_json::json!({ "file": fname }))
}

// ── Audio / media ─────────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct ScanDirRequest {
    dir_path: String,
}

/// Scans a directory for audio files.
#[tauri::command]
fn scan_audio_dir(request: ScanDirRequest) -> Result<serde_json::Value, String> {
    let p = PathBuf::from(&request.dir_path);
    if !p.is_dir() {
        return Err(format!("Directory not found: {}", request.dir_path));
    }

    let audio_extensions = [".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"];
    let mut files: Vec<serde_json::Value> = Vec::new();

    fn walk(dir: &Path, extensions: &[&str], base: &Path, files: &mut Vec<serde_json::Value>) {
        if let Ok(entries) = fs::read_dir(dir) {
            let mut sorted: Vec<_> = entries.flatten().collect();
            sorted.sort_by_key(|e| e.file_name());
            for entry in sorted {
                let path = entry.path();
                if path.is_dir() {
                    walk(&path, extensions, base, files);
                } else if path.is_file() {
                    let ext = path.extension()
                        .map(|e| format!(".{}", e.to_string_lossy().to_lowercase()))
                        .unwrap_or_default();
                    if extensions.contains(&ext.as_str()) {
                        let rel = path.strip_prefix(base)
                            .map(|r| r.to_string_lossy().replace('\\', "/"))
                            .unwrap_or_default();
                        let size = fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
                        files.push(serde_json::json!({
                            "name": path.file_name().unwrap_or_default().to_string_lossy(),
                            "rel_path": rel,
                            "path": path.to_string_lossy().replace('\\', "/"),
                            "size": size,
                            "size_bytes": size,
                        }));
                    }
                }
            }
        }
    }

    walk(&p, &audio_extensions, &p, &mut files);

    Ok(serde_json::json!({
        "directory": p.to_string_lossy().replace('\\', "/"),
        "total_files": files.len(),
        "files": files,
        "audio_files": files,
    }))
}

// ── System ────────────────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct RevealRequest {
    path: String,
}

/// Opens a path in the OS file explorer.
#[tauri::command]
fn reveal_in_explorer(_app_handle: AppHandle, request: RevealRequest) -> Result<(), String> {
    let path = PathBuf::from(&request.path);
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        if path.is_file() {
            let _ = Command::new("explorer")
                .args(["/select,", &path.to_string_lossy()])
                .spawn();
        } else {
            let _ = Command::new("explorer")
                .arg(&path.to_string_lossy().to_string())
                .spawn();
        }
    }
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        let _ = Command::new("open").arg("-R").arg(&path).spawn();
    }
    #[cfg(target_os = "linux")]
    {
        use std::process::Command;
        let _ = Command::new("xdg-open")
            .arg(path.parent().unwrap_or(&path))
            .spawn();
    }
    Ok(())
}

// ── Utilities ─────────────────────────────────────────────────────────────────

fn sanitize_filename(name: &str) -> String {
    let safe: String = name
        .chars()
        .map(|c| {
            if matches!(c, '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|') {
                '_'
            } else {
                c
            }
        })
        .collect();
    let trimmed = safe.trim().trim_start_matches('.').to_string();
    if trimmed.is_empty() { "project.qproj".to_string() } else { trimmed }
}

fn unique_path(dir: &Path, name: &str) -> PathBuf {
    let path = dir.join(name);
    if !path.exists() {
        return path;
    }
    let stem = Path::new(name)
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default();
    let ext = Path::new(name)
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy()))
        .unwrap_or_default();
    for i in 2..100 {
        let candidate = dir.join(format!("{} ({}){}", stem, i, ext));
        if !candidate.exists() {
            return candidate;
        }
    }
    dir.join(format!("{}_{}{}", stem, std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0), ext))
}

// ── App entry point ───────────────────────────────────────────────────────────

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(err) = engine_manager::start_engine(handle.clone(), false).await {
                    eprintln!("[QuranReciteToText] Engine initialization error: {}", err);
                    engine_manager::set_status_error(&handle, &err);
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            // Core
            get_app_version,
            get_engine_status,
            is_engine_installed,
            ensure_engine,
            // Alignment
            run_align,
            stop_align,
            segment_quran_audio_local_word_timing,
            check_local_segmentation_ready,
            install_local_segmentation_deps,
            // Projects
            list_projects,
            load_project,
            save_project,
            create_project,
            delete_project,
            duplicate_project,
            // Audio
            scan_audio_dir,
            waveform::get_audio_waveform,
            waveform::get_duration,
            waveform::cut_audio,
            waveform::diagnose_media_binaries,
            waveform::audio_timestamp_stretch_ms,
            waveform::normalize_audio_timestamps,
            // System
            reveal_in_explorer,
            waveform::open_explorer_with_file_selected,
        ])
        .build(tauri::generate_context!())
        .expect("error while building Quran Recite2Text application")
        .run(|_app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                engine_manager::stop_engine();
            }
        });
}
