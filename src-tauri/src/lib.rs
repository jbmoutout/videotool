mod models;
mod config;
mod cli;
mod util;
mod viewer;
mod commands;

use std::sync::{Arc, Mutex};
use tauri::Manager;

use models::{AppState, ChildHandle};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let child_handle: ChildHandle = Arc::new(Mutex::new(None));
    let child_for_event = child_handle.clone();
    let viewer_server_port: Arc<Mutex<Option<u16>>> = Arc::new(Mutex::new(None));

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState {
            child: child_handle,
            viewer_server_port,
            viewer_project_dir: Arc::new(Mutex::new(String::new())),
        })
        .on_window_event(move |_window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(mut child) = child_for_event.lock().unwrap().take() {
                    let _ = child.start_kill();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::start_pipeline,
            commands::load_topics,
            commands::load_beats,
            commands::start_viewer_server,
            commands::cancel_pipeline,
            commands::list_projects,
            commands::seed_demo_project,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
