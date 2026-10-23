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

    let mut projects_with_time: Vec<(std::time::SystemTime, serde_json::Value)> = Vec::new();

    for entry in fs::read_dir(&projects_dir).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        let mut path = entry.path();
        if !path.is_file() {
            continue;
        }

        // Auto-migrate extensionless legacy files (e.g. "qproj", "qproj (4)")
        let is_qproj = path.extension().map(|e| e == "qproj").unwrap_or(false);
        let is_part = path.extension().map(|e| e == "part").unwrap_or(false);
        if !is_qproj && !is_part {
            if let Ok(content) = fs::read_to_string(&path) {
                if let Ok(mut data) = serde_json::from_str::<serde_json::Value>(&content) {
                    if data.get("surahs").is_some() || data.get("app_version").is_some() || data.get("project_name").is_some() {
                        let fname_stem = path.file_name().unwrap_or_default().to_string_lossy().to_string();
                        let target_name = format!("{}.qproj", fname_stem);
                        let target_path = projects_dir.join(&target_name);
                        let final_path = if !target_path.exists() {
                            let _ = fs::rename(&path, &target_path);
                            target_path
                        } else {
                            path.clone()
                        };

                        if let Some(obj) = data.as_object_mut() {
                            let clean_fname = final_path.file_name().unwrap_or_default().to_string_lossy().to_string();
                            obj.insert("file_name".to_string(), serde_json::json!(clean_fname.clone()));
                            obj.insert("_file".to_string(), serde_json::json!(clean_fname.clone()));
                            obj.insert("_path".to_string(), serde_json::json!(final_path.to_string_lossy().to_string()));
                            let cur_name = obj.get("project_name").and_then(|v| v.as_str()).unwrap_or("");
                            if cur_name == "." || cur_name.is_empty() {
                                // Try to extract meaningful name from first surah
                                let derived_name = obj.get("surahs")
                                    .and_then(|s| s.as_array())
                                    .and_then(|arr| arr.first())
                                    .and_then(|s0| s0.get("surah_name_arabic").or_else(|| s0.get("surah_name_english")))
                                    .and_then(|v| v.as_str())
                                    .unwrap_or(&fname_stem);
                                obj.insert("project_name".to_string(), serde_json::json!(derived_name));
                            }
                        }
                        let _ = fs::write(&final_path, serde_json::to_string_pretty(&data).unwrap_or_default());
                        path = final_path;
                    }
                }
            }
        }

        if path.extension().map(|e| e == "qproj").unwrap_or(false) {
            if let Ok(content) = fs::read_to_string(&path) {
                if let Ok(mut data) = serde_json::from_str::<serde_json::Value>(&content) {
                    let fname = path.file_name().unwrap_or_default().to_string_lossy().to_string();
                    let mtime = fs::metadata(&path).and_then(|m| m.modified()).unwrap_or(std::time::SystemTime::UNIX_EPOCH);
                    if let Some(obj) = data.as_object_mut() {
                        obj.insert("file_name".to_string(), serde_json::json!(fname.clone()));
                        obj.insert("_file".to_string(), serde_json::json!(fname.clone()));
                        obj.insert("_path".to_string(), serde_json::json!(path.to_string_lossy().to_string()));
                        let pname = obj.get("project_name").and_then(|v| v.as_str()).unwrap_or("");
                        if pname == "." || pname.is_empty() {
                            let derived = obj.get("surahs")
                                .and_then(|s| s.as_array())
                                .and_then(|arr| arr.first())
                                .and_then(|s0| s0.get("surah_name_arabic").or_else(|| s0.get("surah_name_english")))
                                .and_then(|v| v.as_str())
                                .map(|s| s.to_string())
                                .unwrap_or_else(|| fname.trim_end_matches(".qproj").to_string());
                            obj.insert("project_name".to_string(), serde_json::json!(derived));
                        }
                    }
                    projects_with_time.push((mtime, data));
                }
            }
        }
    }

    // Sort by modified time descending (most recent first)
    projects_with_time.sort_by(|a, b| b.0.cmp(&a.0));
    let projects: Vec<serde_json::Value> = projects_with_time.into_iter().map(|(_, p)| p).collect();

    Ok(serde_json::json!({ "projects": projects }))
}

/// Loads a project by filename.
#[tauri::command]
fn load_project(app_handle: AppHandle, file: String) -> Result<serde_json::Value, String> {
    let projects_dir = get_projects_dir(&app_handle)?;
    let safe_name = sanitize_filename(&file);
    let mut path = projects_dir.join(&safe_name);
    if !path.exists() {
        let direct_path = projects_dir.join(&file);
        if direct_path.exists() {
            path = direct_path;
        } else {
            let with_ext = projects_dir.join(format!("{}.qproj", file.trim_end_matches(".qproj")));
            if with_ext.exists() {
                path = with_ext;
            } else {
                return Err(format!("Project file not found: {}", file));
            }
        }
    }
    let content = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut data: serde_json::Value = serde_json::from_str(&content).map_err(|e| e.to_string())?;
    let fname = path.file_name().unwrap_or_default().to_string_lossy().to_string();
    if let Some(obj) = data.as_object_mut() {
        obj.insert("file_name".to_string(), serde_json::json!(fname.clone()));
        obj.insert("_file".to_string(), serde_json::json!(fname.clone()));
        obj.insert("_path".to_string(), serde_json::json!(path.to_string_lossy().to_string()));
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

    let safe_name = sanitize_filename(&request.name);
    let dest = unique_path(&projects_dir, &safe_name);

    let fname = dest.file_name().unwrap_or_default().to_string_lossy().to_string();
    let clean_project_name = if request.name.trim() == "." || request.name.trim().is_empty() {
        fname.trim_end_matches(".qproj").to_string()
    } else {
        request.name.trim().to_string()
    };

    let mut data = request.data;
    if let Some(obj) = data.as_object_mut() {
        obj.insert("file_name".to_string(), serde_json::json!(fname.clone()));
        obj.insert("_file".to_string(), serde_json::json!(fname.clone()));
        obj.insert("_path".to_string(), serde_json::json!(dest.to_string_lossy().to_string()));
        obj.insert("project_name".to_string(), serde_json::json!(clean_project_name));
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
    let mut src = projects_dir.join(sanitize_filename(&request.file));
    if !src.exists() {
        src = projects_dir.join(&request.file);
    }
    if !src.exists() {
        return Err(format!("Project not found: {}", request.file));
    }

    let stem = src.file_stem().unwrap_or_default().to_string_lossy().to_string();
    let copy_name = format!("{} Copy.qproj", stem);
    let dest = unique_path(&projects_dir, &copy_name);
    let dest_fname = dest.file_name().unwrap_or_default().to_string_lossy().to_string();
    let dest_stem = dest_fname.trim_end_matches(".qproj").to_string();

    if let Ok(content) = fs::read_to_string(&src) {
        if let Ok(mut data) = serde_json::from_str::<serde_json::Value>(&content) {
            if let Some(obj) = data.as_object_mut() {
                obj.insert("file_name".to_string(), serde_json::json!(dest_fname.clone()));
                obj.insert("_file".to_string(), serde_json::json!(dest_fname.clone()));
                obj.insert("_path".to_string(), serde_json::json!(dest.to_string_lossy().to_string()));
                obj.insert("project_name".to_string(), serde_json::json!(dest_stem));
            }
            let json_str = serde_json::to_string_pretty(&data).map_err(|e| e.to_string())?;
            fs::write(&dest, json_str).map_err(|e| e.to_string())?;
            return Ok(serde_json::json!({ "file": dest_fname }));
        }
    }

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
fn reveal_in_explorer(app_handle: AppHandle, request: RevealRequest) -> Result<(), String> {
    let mut path = PathBuf::from(&request.path);
    if !path.exists() {
        if let Ok(projects_dir) = get_projects_dir(&app_handle) {
            if request.path == "projects" || request.path.is_empty() {
                path = projects_dir;
            } else {
                let candidate = projects_dir.join(&request.path);
                if candidate.exists() {
                    path = candidate;
                } else {
                    let with_ext = projects_dir.join(format!("{}.qproj", request.path.trim_end_matches(".qproj")));
                    if with_ext.exists() {
                        path = with_ext;
                    }
                }
            }
        }
    }

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

#[derive(Debug, Deserialize)]
struct SaveFilePathRequest {
    path: String,
    content: String,
}

/// Writes arbitrary text content directly to a user-chosen destination file path.
#[tauri::command]
fn save_file_to_path(request: SaveFilePathRequest) -> Result<(), String> {
    let p = PathBuf::from(&request.path);
    if let Some(parent) = p.parent() {
        let _ = fs::create_dir_all(parent);
    }
    fs::write(&p, request.content).map_err(|e| format!("Failed to write file to path: {}", e))
}

// ── Utilities ─────────────────────────────────────────────────────────────────

fn sanitize_filename(name: &str) -> String {
    let raw = name.trim();
    let stem = if raw.to_lowercase().ends_with(".qproj") {
        &raw[..raw.len() - 6]
    } else {
        raw
    };

    let safe_stem: String = stem
        .chars()
        .map(|c| {
            if matches!(c, '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' | '\0') {
                '_'
            } else {
                c
            }
        })
        .collect();

    let trimmed = safe_stem.trim().trim_matches('.').trim().to_string();
    let final_stem = if trimmed.is_empty() {
        "Recitation Project".to_string()
    } else {
        trimmed
    };

    format!("{}.qproj", final_stem)
}

fn unique_path(dir: &Path, name: &str) -> PathBuf {
    let path = dir.join(name);
    if !path.exists() {
        return path;
    }
    let stem = Path::new(name)
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "Recitation Project".to_string());
    let ext = ".qproj";
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
            save_file_to_path,
        ])
        .build(tauri::generate_context!())
        .expect("error while building Quran Recite2Text application")
        .run(|_app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                engine_manager::stop_engine();
            }
        });
}
