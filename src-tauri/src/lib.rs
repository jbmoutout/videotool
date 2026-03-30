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

// ── proxy config ─────────────────────────────────────────────────────────────

/// Proxy URL: runtime env var (dev) takes priority over compile-time value (release).
/// Filters out empty strings so the Python CLI sees None instead of "".
fn get_proxy_url() -> Option<String> {
    std::env::var("VITE_API_PROXY_URL")
        .ok()
        .or_else(|| option_env!("VITE_API_PROXY_URL").map(String::from))
        .filter(|s| !s.is_empty())
}

/// Proxy auth token: runtime env var (dev) takes priority over compile-time value (release).
fn get_proxy_auth_token() -> Option<String> {
    std::env::var("PROXY_AUTH_TOKEN")
        .ok()
        .or_else(|| option_env!("PROXY_AUTH_TOKEN").map(String::from))
        .filter(|s| !s.is_empty())
}

fn load_env_fallback() {
    let keys = [
        "VITE_API_PROXY_URL",
        "PROXY_AUTH_TOKEN",
        "GROQ_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ];
    let mut missing_any = false;
    for key in keys {
        if std::env::var(key).is_err() {
            missing_any = true;
            break;
        }
    }
    if !missing_any {
        return;
    }

    let mut search_dirs: Vec<std::path::PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        search_dirs.push(cwd);
    }
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(parent) = exe_path.parent() {
            let mut dir = parent.to_path_buf();
            for _ in 0..6 {
                search_dirs.push(dir.clone());
                if let Some(next) = dir.parent() {
                    dir = next.to_path_buf();
                } else {
                    break;
                }
            }
        }
    }

    let mut dotenv_path: Option<std::path::PathBuf> = None;
    for dir in search_dirs {
        let candidate = dir.join(".env");
        if candidate.exists() {
            dotenv_path = Some(candidate);
            break;
        }
    }

    let Some(path) = dotenv_path else { return; };
    let Ok(contents) = std::fs::read_to_string(&path) else { return; };

    for line in contents.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let mut parts = trimmed.splitn(2, '=');
        let key = parts.next().unwrap_or("").trim();
        let mut value = parts.next().unwrap_or("").trim().to_string();
        if key.is_empty() || value.is_empty() {
            continue;
        }
        if (value.starts_with('"') && value.ends_with('"'))
            || (value.starts_with('\'') && value.ends_with('\''))
        {
            value = value[1..value.len() - 1].to_string();
        }
        if std::env::var(key).is_err() {
            std::env::set_var(key, value);
        }
    }
}

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

/// Progress line emitted by `videotool pipeline --json-progress`.
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

/// Error line emitted by `videotool pipeline --json-progress` on failure.
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

/// Summary of a project in the projects/ directory.
#[derive(Debug, Serialize, Clone)]
pub struct ProjectInfo {
    pub project_id: String,
    pub source_filename: String,
    pub title: Option<String>,
    pub channel: Option<String>,
    pub created_at: String,
    pub has_beats: bool,
    pub project_dir: String,
}

/// Response from load_beats: beats data + video file path.
#[derive(Debug, Serialize, Clone)]
pub struct BeatsResponse {
    pub beats: Vec<BeatTopic>,
    pub video_path: Option<String>,
    pub duration_seconds: Option<f64>,
}

// ── Tauri commands ────────────────────────────────────────────────────────────

/// Start the videotool pipeline for the given video path.
/// Spawns subprocess, reads stdout line-by-line in a Tokio task,
/// emits `progress`, `done`, or `error` events to the frontend.
#[tauri::command]
async fn start_pipeline(app: AppHandle, video_path: String, quality: Option<String>) -> Result<(), String> {
    load_env_fallback();
    let cli_path = resolve_cli_path(&app)?;
    let ffmpeg_path = resolve_bundled_tool_path(&app, "ffmpeg");

    // Augment PATH so the subprocess can find ffmpeg/ffprobe regardless of
    // how the app was launched (GUI apps on macOS don't inherit shell PATH).
    let path_env = std::env::var("PATH").unwrap_or_default();
    let ffmpeg_dir = ffmpeg_path.as_ref().and_then(|p| p.parent())
        .map(|p| p.to_string_lossy().to_string());
    let mut path_parts = Vec::new();
    if let Some(dir) = ffmpeg_dir {
        path_parts.push(dir);
    }
    if !path_env.is_empty() {
        path_parts.push(path_env);
    }
    path_parts.extend([
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ].iter().map(|s| s.to_string()));
    let augmented_path = path_parts.join(":");

    eprintln!("[videotool-app] cli_path = {:?}", cli_path);
    eprintln!("[videotool-app] video_path = {:?}", video_path);
    eprintln!("[videotool-app] PATH = {}", augmented_path);
    if let Some(path) = ffmpeg_path.as_ref() {
        eprintln!("[videotool-app] ffmpeg_path = {:?}", path);
    }

    let quality_val = quality.unwrap_or_else(|| "worst".to_string());
    let mut cmd = Command::new(&cli_path);
    cmd.args(["beats", &video_path, "--json-progress", "--quality", &quality_val])
        .env("PATH", augmented_path)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true);

    // Forward proxy config so the bundled Python CLI can reach the API proxy.
    let proxy_url = get_proxy_url();
    let proxy_token = get_proxy_auth_token();
    eprintln!("[videotool-app] proxy_url present: {}, compile-time present: {}, runtime present: {}",
        proxy_url.is_some(),
        option_env!("VITE_API_PROXY_URL").is_some(),
        std::env::var("VITE_API_PROXY_URL").is_ok());
    if let Some(url) = proxy_url {
        cmd.env("VITE_API_PROXY_URL", &url);
        eprintln!("[videotool-app] forwarding VITE_API_PROXY_URL (len={})", url.len());
    }
    if let Some(token) = proxy_token {
        cmd.env("PROXY_AUTH_TOKEN", &token);
    }
    if let Some(path) = ffmpeg_path {
        cmd.env("VIDEOTOOL_FFMPEG_PATH", path.to_string_lossy().to_string());
    }

    let mut child = cmd.spawn()
        .map_err(|e| format!("Failed to spawn videotool: {e}"))?;

    let stdout = child.stdout.take().ok_or("Could not capture stdout")?;
    let stderr = child.stderr.take();
    let last_stderr = Arc::new(Mutex::new(String::new()));

    if let Some(stderr) = stderr {
        let last_stderr_clone = last_stderr.clone();
        tokio::spawn(async move {
            let reader = BufReader::new(stderr);
            let mut lines = reader.lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let line = line.trim().to_string();
                if line.is_empty() {
                    continue;
                }
                eprintln!("[videotool-app] stderr: {line}");
                *last_stderr_clone.lock().unwrap() = line;
            }
        });
    }

    // Clone the child handle arc so the spawned task owns it directly —
    // avoids borrowing `state` across the async boundary.
    let child_handle = app.state::<AppState>().child.clone();
    *child_handle.lock().unwrap() = Some(child);

    let app_clone = app.clone();
    tokio::spawn(async move {
        let reader = BufReader::new(stdout);
        let mut lines = reader.lines();
        let mut got_terminal = false;
        let mut last_non_json = String::new();

        loop {
            match lines.next_line().await {
                Ok(Some(line)) => {
                    let line = line.trim().to_string();
                    if line.is_empty() {
                        continue;
                    }
                    got_terminal |= parse_and_emit(&app_clone, &line, &mut last_non_json);
                }
                Ok(None) => break,
                Err(e) => {
                    let _ = app_clone.emit("pipeline-error", format!("stdout read error: {e}"));
                    got_terminal = true;
                    break;
                }
            }
        }

        // Reap child process and check exit status.
        let maybe_child = child_handle.lock().unwrap().take();
        if let Some(mut child) = maybe_child {
            match child.wait().await {
                Ok(status) if !got_terminal => {
                    // Subprocess ended without emitting done or error — something crashed.
                    let stderr_line = last_stderr.lock().unwrap().clone();
                    let detail = if !last_non_json.is_empty() {
                        format!(": {}", last_non_json)
                    } else if !stderr_line.is_empty() {
                        format!(": {}", stderr_line)
                    } else {
                        String::new()
                    };
                    let msg = if status.success() {
                        format!("Pipeline ended without producing results{detail}")
                    } else {
                        let code = status.code().map(|c| c.to_string()).unwrap_or("signal".into());
                        format!("Pipeline process failed (exit code {code}){detail}")
                    };
                    let _ = app_clone.emit("pipeline-error", msg);
                }
                Err(e) if !got_terminal => {
                    let _ = app_clone.emit("pipeline-error", format!("Failed to reap pipeline process: {e}"));
                }
                _ => {}
            }
        } else if !got_terminal {
            // Child was taken (cancelled) — no error needed unless no terminal event.
            // cancel_pipeline already handles UI reset, so this is a no-op.
        }

        let _ = app_clone.emit("pipeline-exit", ());
    });

    Ok(())
}

/// Parse a single stdout line and emit the right Tauri event.
/// Returns `true` if a terminal event (done, error, beats_ready) was emitted.
fn parse_and_emit(app: &AppHandle, line: &str, last_non_json: &mut String) -> bool {
    let Ok(value) = serde_json::from_str::<serde_json::Value>(line) else {
        // Non-JSON (Python warning/traceback) — log for debugging and keep
        // the last line so we can include it in crash error messages.
        eprintln!("[videotool-app] subprocess: {line}");
        *last_non_json = line.to_string();
        return false;
    };

    if value.get("done").and_then(|v| v.as_bool()) == Some(true) {
        if let Ok(msg) = serde_json::from_value::<DoneMsg>(value) {
            let _ = app.emit("pipeline-done", msg);
            return true;
        }
    } else if value.get("error").is_some() {
        if let Ok(msg) = serde_json::from_value::<ErrorMsg>(value) {
            let _ = app.emit("pipeline-error-msg", msg);
            return true;
        } else {
            eprintln!("[videotool-app] failed to deserialize error line: {line}");
        }
    } else if value.get("step").is_some() {
        if let Ok(msg) = serde_json::from_value::<ProgressMsg>(value) {
            let _ = app.emit("pipeline-progress", msg);
        } else {
            eprintln!("[videotool-app] failed to deserialize progress line: {line}");
        }
    }

    false
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

    eprintln!("[videotool-app] viewer server starting on http://127.0.0.1:{port}");

    tokio::spawn(async move {
        axum::serve(listener, router)
            .await
            .unwrap_or_else(|e| eprintln!("[videotool-app] viewer server error: {e}"));
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

/// Seed a demo project into ~/.videotool/projects/ if it doesn't already exist.
/// Returns true if the demo was written, false if it already existed.
#[tauri::command]
fn seed_demo_project() -> Result<bool, String> {
    let home = std::env::var("HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_default();
    let demo_dir = home.join(".videotool").join("projects").join("demo_sample");

    if demo_dir.join("beats.json").exists() {
        return Ok(false);
    }

    std::fs::create_dir_all(&demo_dir)
        .map_err(|e| format!("Failed to create demo dir: {e}"))?;

    let meta = include_str!("demo/meta.json");
    let beats = include_str!("demo/beats.json");

    std::fs::write(demo_dir.join("meta.json"), meta)
        .map_err(|e| format!("Failed to write demo meta: {e}"))?;
    std::fs::write(demo_dir.join("beats.json"), beats)
        .map_err(|e| format!("Failed to write demo beats: {e}"))?;

    Ok(true)
}

/// List all projects in the projects/ directory.
#[tauri::command]
fn list_projects() -> Result<Vec<ProjectInfo>, String> {
    let home = std::env::var("HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_default();
    let projects_dir = home.join(".videotool").join("projects");

    if !projects_dir.exists() {
        return Ok(vec![]);
    }

    let mut results = Vec::new();

    let entries = std::fs::read_dir(&projects_dir)
        .map_err(|e| format!("Failed to read projects dir: {e}"))?;

    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }

        let meta_path = path.join("meta.json");
        if !meta_path.exists() {
            continue;
        }

        let Ok(data) = std::fs::read_to_string(&meta_path) else {
            continue;
        };
        let Ok(meta) = serde_json::from_str::<serde_json::Value>(&data) else {
            continue;
        };

        let project_id = meta.get("project_id")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string();
        let source_filename = meta.get("source_filename")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();
        let title = meta.get("title")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let channel = meta.get("channel")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let created_at = meta.get("created_at")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let has_beats = path.join("beats.json").exists();

        results.push(ProjectInfo {
            project_id,
            source_filename,
            title,
            channel,
            created_at,
            has_beats,
            project_dir: path.to_string_lossy().to_string(),
        });
    }

    // Sort by created_at descending (newest first)
    results.sort_by(|a, b| b.created_at.cmp(&a.created_at));

    Ok(results)
}

/// Cancel the running pipeline (kill subprocess).
#[tauri::command]
fn cancel_pipeline(app: AppHandle) {
    if let Some(mut child) = app.state::<AppState>().child.lock().unwrap().take() {
        let _ = child.start_kill();
    }
}

// ── helpers ───────────────────────────────────────────────────────────────────

/// Resolve the path to the bundled `videotool` CLI binary.
/// In dev: uses system PATH. In release: bundled inside the app Resources.
fn resolve_cli_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    // Release: binary is bundled via tauri.conf.json `externalBin`.
    if let Ok(resource_path) = app.path().resource_dir() {
        let mut searched_dirs = Vec::new();
        let mut candidates: Vec<std::path::PathBuf> = Vec::new();
        let mut skip_name: Option<String> = None;

        let mut extra_dir: Option<std::path::PathBuf> = None;
        if let Ok(exe_path) = std::env::current_exe() {
            if let Some(parent) = exe_path.parent() {
                extra_dir = Some(parent.to_path_buf());
            }
            if let Some(name) = exe_path.file_name().and_then(|n| n.to_str()) {
                skip_name = Some(name.to_string());
            }
        }

        let mut dirs = vec![resource_path.clone(), resource_path.join("binaries")];
        if let Some(dir) = extra_dir {
            if !dirs.iter().any(|existing| existing == &dir) {
                dirs.push(dir);
            }
        }

        for dir in dirs {
            searched_dirs.push(dir.to_string_lossy().to_string());
            if let Ok(entries) = std::fs::read_dir(&dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if !path.is_file() {
                        continue;
                    }
                    let name = entry.file_name().to_string_lossy().to_string();
                    if skip_name.as_deref() == Some(&name) {
                        continue;
                    }
                    let is_exact = name == "videotool" || name == "videotool.exe";
                    let is_prefixed = name.starts_with("videotool-") || name.starts_with("videotool_");
                    if is_exact || is_prefixed {
                        candidates.push(path);
                    }
                }
            }
        }

        if !candidates.is_empty() {
            let arch = std::env::consts::ARCH;
            candidates.sort_by(|a, b| {
                let a_name = a.file_name().and_then(|n| n.to_str()).unwrap_or("");
                let b_name = b.file_name().and_then(|n| n.to_str()).unwrap_or("");

                let a_score = {
                    let mut s = 0;
                    if a_name == "videotool" || a_name == "videotool.exe" { s += 100; }
                    if a_name.contains(arch) { s += 50; }
                    if a_name.starts_with("videotool-") || a_name.starts_with("videotool_") { s += 10; }
                    s
                };
                let b_score = {
                    let mut s = 0;
                    if b_name == "videotool" || b_name == "videotool.exe" { s += 100; }
                    if b_name.contains(arch) { s += 50; }
                    if b_name.starts_with("videotool-") || b_name.starts_with("videotool_") { s += 10; }
                    s
                };

                b_score.cmp(&a_score).then_with(|| a_name.cmp(b_name))
            });

            let chosen = candidates.remove(0);
            if cfg!(debug_assertions) {
                eprintln!("[videotool-app] resolved cli_path = {:?}", chosen);
            }
            return Ok(chosen);
        }

        if cfg!(debug_assertions) {
            let fallback = std::path::PathBuf::from("videotool");
            eprintln!("[videotool-app] resolved cli_path (PATH fallback) = {:?}", fallback);
            return Ok(fallback);
        }

        let expected = "videotool, videotool.exe, videotool-<target>, videotool_<target>";
        return Err(format!(
            "Bundled videotool binary not found. Searched: {}. Expected one of: {}",
            searched_dirs.join(", "),
            expected
        ));
    }

    // Dev fallback: use PATH.
    if cfg!(debug_assertions) {
        let fallback = std::path::PathBuf::from("videotool");
        eprintln!("[videotool-app] resolved cli_path (PATH fallback) = {:?}", fallback);
        Ok(fallback)
    } else {
        Err("Bundled videotool binary not found (resource_dir unavailable)".to_string())
    }
}

/// Resolve a bundled tool path (e.g., ffmpeg) from common resource locations.
fn resolve_bundled_tool_path(app: &AppHandle, base_name: &str) -> Option<std::path::PathBuf> {
    let mut dirs: Vec<std::path::PathBuf> = Vec::new();
    if let Ok(resource_path) = app.path().resource_dir() {
        dirs.push(resource_path.clone());
        dirs.push(resource_path.join("binaries"));
    }

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(parent) = exe_path.parent() {
            let dir = parent.to_path_buf();
            if !dirs.iter().any(|existing| existing == &dir) {
                dirs.push(dir);
            }
        }
    }

    if dirs.is_empty() {
        return None;
    }

    let mut candidates: Vec<std::path::PathBuf> = Vec::new();
    let exe_name = format!("{base_name}.exe");
    let prefix_dash = format!("{base_name}-");
    let prefix_underscore = format!("{base_name}_");

    for dir in dirs {
        if let Ok(entries) = std::fs::read_dir(&dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if !path.is_file() {
                    continue;
                }
                let name = entry.file_name().to_string_lossy().to_string();
                let is_exact = name == base_name || name == exe_name;
                let is_prefixed = name.starts_with(&prefix_dash) || name.starts_with(&prefix_underscore);
                if is_exact || is_prefixed {
                    candidates.push(path);
                }
            }
        }
    }

    if candidates.is_empty() {
        return None;
    }

    let arch = std::env::consts::ARCH;
    candidates.sort_by(|a, b| {
        let a_name = a.file_name().and_then(|n| n.to_str()).unwrap_or("");
        let b_name = b.file_name().and_then(|n| n.to_str()).unwrap_or("");

        let a_score = {
            let mut s = 0;
            if a_name == base_name || a_name == exe_name { s += 100; }
            if a_name.contains(arch) { s += 50; }
            if a_name.starts_with(&prefix_dash) || a_name.starts_with(&prefix_underscore) { s += 10; }
            s
        };
        let b_score = {
            let mut s = 0;
            if b_name == base_name || b_name == exe_name { s += 100; }
            if b_name.contains(arch) { s += 50; }
            if b_name.starts_with(&prefix_dash) || b_name.starts_with(&prefix_underscore) { s += 10; }
            s
        };

        b_score.cmp(&a_score).then_with(|| a_name.cmp(b_name))
    });

    candidates.into_iter().next()
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
            list_projects,
            seed_demo_project,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
