mod process_utils;
mod engine_manager;

use tauri::AppHandle;

#[tauri::command]
fn get_app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
fn get_engine_status() -> engine_manager::EngineStatus {
    engine_manager::get_engine_status()
}

#[tauri::command]
fn get_engine_port() -> u16 {
    engine_manager::get_engine_port()
}

#[tauri::command]
fn get_engine_url() -> String {
    format!("http://127.0.0.1:{}", engine_manager::get_engine_port())
}

#[tauri::command]
async fn ensure_engine(app_handle: AppHandle) -> Result<engine_manager::EngineStatus, String> {
    engine_manager::start_engine(app_handle).await?;
    Ok(engine_manager::get_engine_status())
}

#[tauri::command]
fn is_engine_installed(app_handle: AppHandle) -> bool {
    engine_manager::is_environment_fully_installed(&app_handle)
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(err) = engine_manager::start_engine(handle.clone()).await {
                    eprintln!("[QuranReciteToText] Engine initialization error: {}", err);
                    engine_manager::set_status_error(&handle, &err);
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_app_version,
            get_engine_status,
            get_engine_port,
            get_engine_url,
            ensure_engine,
            is_engine_installed
        ])
        .build(tauri::generate_context!())
        .expect("error while building Quran Recite2Text application")
        .run(|_app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                engine_manager::stop_engine();
            }
        });
}
