use axum::body::Body;
use axum::extract::State as AxumState;
use axum::http::{HeaderMap, StatusCode};
use axum::response::IntoResponse;
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncSeekExt, BufReader};
use tokio::process::{Child, Command};
use tokio_util::io::ReaderStream;

// ── shared state ──────────────────────────────────────────────────────────────

/// Holds the running subprocess so we can kill it on app close.
type ChildHandle = Arc<Mutex<Option<Child>>>;

struct AppState {
    child: ChildHandle,
    viewer_server_port: Arc<Mutex<Option<u16>>>,
    viewer_project_dir: Arc<Mutex<String>>,
}

/// Shared state for the axum video/viewer server.
#[derive(Clone)]
struct ViewerServerState {
    project_dir: Arc<Mutex<String>>,
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
    #[serde(default)]
    pub download_pct: Option<u32>,
}

/// Error line emitted by `vodtool pipeline --json-progress` on failure.
/// {"error":"Transcription failed","step":2}
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ErrorMsg {
    pub error: String,
    pub step: u32,
}

/// Done line emitted after pipeline succeeds.
/// {"done":true,"project_dir":"/...","topic_count":7}
/// Beats pipeline also adds: {"done":true,"project_dir":"/...","topic_count":6,"beat_count":18}
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct DoneMsg {
    pub done: bool,
    pub project_dir: String,
    #[serde(default)]
    pub topic_count: u32,
    #[serde(default)]
    pub beat_count: u32,
}

/// Beats-ready line: beats are done, video may still be downloading.
/// {"beats_ready":true,"project_dir":"/...","topic_count":6,"beat_count":18}
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct BeatsReadyMsg {
    pub beats_ready: bool,
    pub project_dir: String,
    #[serde(default)]
    pub topic_count: u32,
    #[serde(default)]
    pub beat_count: u32,
}

/// Video-ready line: video download + remux complete.
/// {"video_ready":true,"project_dir":"/..."}
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct VideoReadyMsg {
    pub video_ready: bool,
    pub project_dir: String,
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

/// Beat entry for a single narrative beat within a topic.
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct BeatEntry {
    #[serde(rename = "type")]
    pub beat_type: String,
    pub start_s: f64,
    pub end_s: f64,
    pub confidence: f64,
    pub label: String,
}

/// Topic with narrative beats from beats.json.
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct BeatTopic {
    pub topic_id: String,
    pub topic_label: String,
    pub beats: Vec<BeatEntry>,
}

/// Wrapper for beats.json.
#[derive(Debug, Deserialize, Serialize, Clone)]
struct BeatsFile {
    beats: Vec<BeatTopic>,
}

/// Response from load_beats: beats data + video file path.
#[derive(Debug, Serialize, Clone)]
pub struct BeatsResponse {
    pub beats: Vec<BeatTopic>,
    pub video_path: Option<String>,
    pub duration_seconds: Option<f64>,
}

// ── Tauri commands ────────────────────────────────────────────────────────────

/// Start the vodtool pipeline for the given video path.
/// Spawns subprocess, reads stdout line-by-line in a Tokio task,
/// emits `progress`, `done`, or `error` events to the frontend.
#[tauri::command]
async fn start_pipeline(app: AppHandle, video_path: String, quality: Option<String>) -> Result<(), String> {
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

    let quality_val = quality.unwrap_or_else(|| "worst".to_string());
    let mut child = Command::new(&cli_path)
        .args(["beats", &video_path, "--json-progress", "--quality", &quality_val])
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
    } else if value.get("beats_ready").and_then(|v| v.as_bool()) == Some(true) {
        if let Ok(msg) = serde_json::from_value::<BeatsReadyMsg>(value) {
            let _ = app.emit("pipeline-beats-ready", msg);
        }
    } else if value.get("video_ready").and_then(|v| v.as_bool()) == Some(true) {
        if let Ok(msg) = serde_json::from_value::<VideoReadyMsg>(value) {
            let _ = app.emit("pipeline-video-ready", msg);
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

/// Load beats from project_dir/beats.json + discover video file path.
#[tauri::command]
fn load_beats(project_dir: String) -> Result<BeatsResponse, String> {
    let base = std::path::Path::new(&project_dir);

    // Load beats.json
    let beats_path = base.join("beats.json");
    if !beats_path.exists() {
        return Err(format!("beats.json not found in {project_dir}"));
    }

    let data = std::fs::read_to_string(&beats_path)
        .map_err(|e| format!("Failed to read beats.json: {e}"))?;
    let beats_file: BeatsFile = serde_json::from_str(&data)
        .map_err(|e| format!("Failed to parse beats.json: {e}"))?;

    // Discover video file — check source.* files in project dir
    let video_path = find_video_file(base);

    // Get duration from meta.json
    let duration_seconds = base.join("meta.json")
        .exists()
        .then(|| {
            std::fs::read_to_string(base.join("meta.json"))
                .ok()
                .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
                .and_then(|v| v.get("duration_seconds")?.as_f64())
        })
        .flatten();

    Ok(BeatsResponse {
        beats: beats_file.beats,
        video_path,
        duration_seconds,
    })
}

/// Find the video file in a project directory (source.mp4, source.mkv, etc.).
fn find_video_file(base: &std::path::Path) -> Option<String> {
    let extensions = ["mp4", "mkv", "mov", "avi", "webm", "ts"];
    for ext in &extensions {
        let path = base.join(format!("source.{ext}"));
        if path.exists() {
            return Some(path.to_string_lossy().to_string());
        }
    }
    None
}

// ── viewer server ────────────────────────────────────────────────────────────

/// The embedded viewer HTML (auto-loading variant of beat-viewer.html).
const VIEWER_HTML: &str = include_str!("viewer.html");

/// Start a localhost HTTP server that serves the beat viewer, video, and beats.json.
/// Returns the port number so the frontend can navigate to it.
#[tauri::command]
async fn start_viewer_server(app: AppHandle, project_dir: String) -> Result<u16, String> {
    // Check if server is already running
    let port_handle = app.state::<AppState>().viewer_server_port.clone();
    let shared_dir = app.state::<AppState>().viewer_project_dir.clone();

    // Always update the project dir (so the running server serves the new project)
    *shared_dir.lock().unwrap() = project_dir.clone();

    if let Some(port) = *port_handle.lock().unwrap() {
        // Server already running — project dir updated above, reuse the port
        return Ok(port);
    }

    let state = ViewerServerState {
        project_dir: shared_dir.clone(),
    };

    let cors = tower_http::cors::CorsLayer::permissive();

    let router = axum::Router::new()
        .route("/", axum::routing::get(serve_viewer_html))
        .route("/video", axum::routing::get(serve_video))
        .route("/beats.json", axum::routing::get(serve_beats_json))
        .layer(cors)
        .with_state(state);

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|e| format!("Failed to bind viewer server: {e}"))?;

    let port = listener
        .local_addr()
        .map_err(|e| format!("Failed to get port: {e}"))?
        .port();

    eprintln!("[vodtool-app] viewer server starting on http://127.0.0.1:{port}");

    tokio::spawn(async move {
        axum::serve(listener, router)
            .await
            .unwrap_or_else(|e| eprintln!("[vodtool-app] viewer server error: {e}"));
    });

    *port_handle.lock().unwrap() = Some(port);

    Ok(port)
}

/// Serve the embedded viewer HTML.
async fn serve_viewer_html() -> impl IntoResponse {
    (
        StatusCode::OK,
        [("content-type", "text/html; charset=utf-8")],
        VIEWER_HTML,
    )
}

/// Serve beats.json from the project directory.
async fn serve_beats_json(AxumState(state): AxumState<ViewerServerState>) -> impl IntoResponse {
    let project_dir = state.project_dir.lock().unwrap().clone();
    let path = std::path::Path::new(&project_dir).join("beats.json");
    match tokio::fs::read_to_string(&path).await {
        Ok(data) => (
            StatusCode::OK,
            [("content-type", "application/json")],
            data,
        )
            .into_response(),
        Err(e) => (
            StatusCode::NOT_FOUND,
            format!("beats.json not found: {e}"),
        )
            .into_response(),
    }
}

/// Serve the video file with HTTP Range request support for seeking.
/// Streams all responses — never loads the whole file into memory.
async fn serve_video(
    AxumState(state): AxumState<ViewerServerState>,
    headers: HeaderMap,
) -> impl IntoResponse {
    let project_dir = state.project_dir.lock().unwrap().clone();
    let base = std::path::Path::new(&project_dir);
    let video_path = match find_video_file(base) {
        Some(p) => p,
        None => {
            return (StatusCode::NOT_FOUND, "No video file found").into_response();
        }
    };

    let metadata = match tokio::fs::metadata(&video_path).await {
        Ok(m) => m,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("Cannot read video: {e}"),
            )
                .into_response();
        }
    };

    let file_size = metadata.len();
    let content_type = if video_path.ends_with(".mkv") {
        "video/x-matroska"
    } else if video_path.ends_with(".webm") {
        "video/webm"
    } else {
        "video/mp4"
    };

    // Parse Range header
    if let Some(range_header) = headers.get("range") {
        if let Ok(range_str) = range_header.to_str() {
            if let Some(range) = parse_range(range_str, file_size) {
                let (start, end) = range;
                let length = end - start + 1;

                let mut file = match tokio::fs::File::open(&video_path).await {
                    Ok(f) => f,
                    Err(e) => {
                        return (
                            StatusCode::INTERNAL_SERVER_ERROR,
                            format!("Cannot open video: {e}"),
                        )
                            .into_response();
                    }
                };

                if file.seek(std::io::SeekFrom::Start(start)).await.is_err() {
                    return (StatusCode::INTERNAL_SERVER_ERROR, "Seek failed")
                        .into_response();
                }

                // Stream the range — .take() caps bytes without loading into memory
                let limited = file.take(length);
                let stream = ReaderStream::new(limited);
                let body = Body::from_stream(stream);

                let content_range = format!("bytes {start}-{end}/{file_size}");
                let len_str = length.to_string();

                return match axum::http::Response::builder()
                    .status(StatusCode::PARTIAL_CONTENT)
                    .header("content-type", content_type)
                    .header("accept-ranges", "bytes")
                    .header("content-range", content_range)
                    .header("content-length", len_str)
                    .body(body)
                {
                    Ok(resp) => resp.into_response(),
                    Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Response build failed").into_response(),
                };
            }
        }
    }

    // No Range header — stream the full file (never load into memory)
    let file = match tokio::fs::File::open(&video_path).await {
        Ok(f) => f,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("Cannot read video: {e}"),
            )
                .into_response();
        }
    };

    let stream = ReaderStream::new(file);
    let body = Body::from_stream(stream);
    let len_str = file_size.to_string();

    match axum::http::Response::builder()
        .status(StatusCode::OK)
        .header("content-type", content_type)
        .header("accept-ranges", "bytes")
        .header("content-length", len_str)
        .body(body)
    {
        Ok(resp) => resp.into_response(),
        Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Response build failed").into_response(),
    }
}

/// Parse an HTTP Range header like "bytes=START-", "bytes=START-END", or "bytes=-N" (suffix).
fn parse_range(range_str: &str, file_size: u64) -> Option<(u64, u64)> {
    if file_size == 0 {
        return None;
    }

    let range_str = range_str.strip_prefix("bytes=")?;
    let parts: Vec<&str> = range_str.splitn(2, '-').collect();
    if parts.len() != 2 {
        return None;
    }

    // Suffix range: "bytes=-500" means last 500 bytes
    if parts[0].is_empty() {
        let suffix_len: u64 = parts[1].parse().ok()?;
        if suffix_len == 0 {
            return None;
        }
        let start = file_size.saturating_sub(suffix_len);
        return Some((start, file_size - 1));
    }

    let start: u64 = parts[0].parse().ok()?;
    let end: u64 = if parts[1].is_empty() {
        file_size - 1
    } else {
        parts[1].parse().ok()?
    };

    if start > end || start >= file_size {
        return None;
    }

    Some((start, end.min(file_size - 1)))
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
            load_beats,
            start_viewer_server,
            cancel_pipeline,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
