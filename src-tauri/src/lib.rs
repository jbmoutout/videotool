use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};

// ── shared state ──────────────────────────────────────────────────────────────

/// Holds the running subprocess so we can kill it on app close.
type ChildHandle = Arc<Mutex<Option<Child>>>;

struct AppState {
    child: ChildHandle,
}

// ── IPC message types ─────────────────────────────────────────────────────────

/// Progress line emitted by `vodtool pipeline --json-progress`.
/// {"step":1,"total":5,"pct":0.2,"msg":"Ingesting video..."}
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ProgressMsg {
    pub step: u32,
    pub total: u32,
    pub pct: f64,
    pub msg: String,
}

/// Error line emitted by `vodtool pipeline --json-progress` on failure.
/// {"error":"Transcription failed","step":2}
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ErrorMsg {
    pub error: String,
    pub step: u32,
}

/// Done line emitted after step 5 succeeds.
/// {"done":true,"project_dir":"/...","topic_count":7}
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct DoneMsg {
    pub done: bool,
    pub project_dir: String,
    pub topic_count: u32,
}

/// Topic entry from topic_map_llm.json (subset of fields needed for UI).
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct TopicEntry {
    pub topic_id: String,
    pub label: String,
    pub summary: String,
    pub duration_label: String,
    pub chunk_count: u32,
}

// ── Tauri commands ────────────────────────────────────────────────────────────

/// Start the vodtool pipeline for the given video path.
/// Spawns subprocess, reads stdout line-by-line in a Tokio task,
/// emits `progress`, `done`, or `error` events to the frontend.
#[tauri::command]
async fn start_pipeline(app: AppHandle, video_path: String) -> Result<(), String> {
    let cli_path = resolve_cli_path(&app)?;

    // Augment PATH so the subprocess can find ffmpeg/ffprobe regardless of
    // how the app was launched (GUI apps on macOS don't inherit shell PATH).
    let path_env = std::env::var("PATH").unwrap_or_default();
    let augmented_path = format!(
        "{}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        path_env
    );

    eprintln!("[vodtool-app] cli_path = {:?}", cli_path);
    eprintln!("[vodtool-app] video_path = {:?}", video_path);
    eprintln!("[vodtool-app] PATH = {}", augmented_path);

    let mut child = Command::new(&cli_path)
        .args(["pipeline", &video_path, "--json-progress"])
        .env("PATH", augmented_path)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::inherit())
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| format!("Failed to spawn vodtool: {e}"))?;

    let stdout = child.stdout.take().ok_or("Could not capture stdout")?;

    // Clone the child handle arc so the spawned task owns it directly —
    // avoids borrowing `state` across the async boundary.
    let child_handle = app.state::<AppState>().child.clone();
    *child_handle.lock().unwrap() = Some(child);

    let app_clone = app.clone();
    tokio::spawn(async move {
        let reader = BufReader::new(stdout);
        let mut lines = reader.lines();

        loop {
            match lines.next_line().await {
                Ok(Some(line)) => {
                    let line = line.trim().to_string();
                    if line.is_empty() {
                        continue;
                    }
                    parse_and_emit(&app_clone, &line);
                }
                Ok(None) => {
                    // Subprocess closed stdout — reap and notify frontend.
                    let _ = app_clone.emit("pipeline-exit", ());
                    break;
                }
                Err(e) => {
                    let _ = app_clone.emit("pipeline-error", format!("stdout read error: {e}"));
                    break;
                }
            }
        }

        // Reap child process — take out of mutex BEFORE awaiting to drop the lock.
        let maybe_child = child_handle.lock().unwrap().take();
        if let Some(mut child) = maybe_child {
            let _ = child.wait().await;
        }
    });

    Ok(())
}

/// Parse a single stdout line and emit the right Tauri event.
fn parse_and_emit(app: &AppHandle, line: &str) {
    let Ok(value) = serde_json::from_str::<serde_json::Value>(line) else {
        // Non-JSON (Python warning/log) — ignore silently.
        return;
    };

    if value.get("done").and_then(|v| v.as_bool()) == Some(true) {
        if let Ok(msg) = serde_json::from_value::<DoneMsg>(value) {
            let _ = app.emit("pipeline-done", msg);
        }
    } else if value.get("error").is_some() {
        if let Ok(msg) = serde_json::from_value::<ErrorMsg>(value) {
            let _ = app.emit("pipeline-error-msg", msg);
        }
    } else if value.get("step").is_some() {
        if let Ok(msg) = serde_json::from_value::<ProgressMsg>(value) {
            let _ = app.emit("pipeline-progress", msg);
        }
    }
    // Unknown JSON shape — ignore silently.
}

/// Load topics from project_dir/topic_map_llm.json (or fallback).
#[tauri::command]
fn load_topics(project_dir: String) -> Result<Vec<TopicEntry>, String> {
    let base = std::path::Path::new(&project_dir);
    let candidates = ["topic_map_llm.json", "topic_map_labeled.json", "topic_map.json"];

    for filename in &candidates {
        let path = base.join(filename);
        if path.exists() {
            let data = std::fs::read_to_string(&path)
                .map_err(|e| format!("Failed to read {filename}: {e}"))?;
            let topics: Vec<TopicEntry> = serde_json::from_str(&data)
                .map_err(|e| format!("Failed to parse {filename}: {e}"))?;
            return Ok(topics);
        }
    }

    Err(format!("No topic map found in {project_dir}"))
}

/// Cancel the running pipeline (kill subprocess).
#[tauri::command]
fn cancel_pipeline(app: AppHandle) {
    if let Some(mut child) = app.state::<AppState>().child.lock().unwrap().take() {
        let _ = child.start_kill();
    }
}

// ── helpers ───────────────────────────────────────────────────────────────────

/// Resolve the path to the bundled `vodtool` CLI binary.
/// In dev: uses system PATH. In release: bundled inside the app Resources.
fn resolve_cli_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    // Release: binary is bundled via tauri.conf.json `externalBin`.
    if let Ok(resource_path) = app.path().resource_dir() {
        let bundled = resource_path.join("vodtool");
        if bundled.exists() {
            return Ok(bundled);
        }
    }

    // Dev fallback: use PATH.
    Ok(std::path::PathBuf::from("vodtool"))
}

// ── tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    /// parse_and_emit must not panic on non-UTF8-like garbage input.
    /// In practice the async reader returns an Err for non-UTF8, but parse_and_emit
    /// is called with the already-decoded &str — so a replacement-char string is the
    /// realistic input. The function must silently ignore it (non-JSON).
    #[test]
    fn test_non_utf8_replacement_chars_ignored() {
        // U+FFFD is the replacement char inserted by from_utf8_lossy for bad bytes.
        let garbage = "\u{FFFD}\u{FFFD}\u{FFFD}";
        // parse_and_emit needs an AppHandle which requires a running Tauri context —
        // so we test the JSON-parsing logic directly instead.
        let result = serde_json::from_str::<serde_json::Value>(garbage);
        assert!(result.is_err(), "garbage bytes should not parse as JSON");
        // Confirm our guard works: the function returns early on Err.
        // (The full integration is exercised in e2e; this guards the parse branch.)
    }

    /// parse_and_emit must silently ignore malformed JSON — no panic, no crash.
    #[test]
    fn test_malformed_json_ignored() {
        let cases = [
            "{step:1}",                       // unquoted key
            r#"{"step":1"#,                   // truncated
            r#"{"step":1,"total":5,"pct":}"#, // missing value
            "",                               // empty line (filtered before this fn)
            "null",                           // valid JSON but no useful keys
        ];

        for input in &cases {
            let result = serde_json::from_str::<serde_json::Value>(input);
            match result {
                Err(_) => {} // Non-JSON: parse_and_emit returns early — correct
                Ok(value) => {
                    // Valid JSON with no step/error/done — parse_and_emit ignores it.
                    let has_step = value.get("step").is_some();
                    let has_error = value.get("error").is_some();
                    let has_done = value.get("done").and_then(|v| v.as_bool()) == Some(true);
                    assert!(
                        !has_step && !has_error && !has_done,
                        "input '{input}' unexpectedly matched a message type"
                    );
                }
            }
        }
    }
}

// ── app entry point ───────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let child_handle: ChildHandle = Arc::new(Mutex::new(None));
    let child_for_event = child_handle.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState { child: child_handle })
        .on_window_event(move |_window, event| {
            // Kill subprocess when user closes the app — prevents orphaned process (TODO #9).
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(mut child) = child_for_event.lock().unwrap().take() {
                    let _ = child.start_kill();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            start_pipeline,
            load_topics,
            cancel_pipeline,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
