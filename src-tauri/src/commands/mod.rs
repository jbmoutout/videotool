use std::sync::Arc;
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

use crate::cli;
use crate::config;
use crate::models::{self, AppState, BeatsFile, BeatsResponse, DoneMsg, ErrorMsg, ProgressMsg, ProjectInfo, TopicEntry, ViewerServerState};
use crate::viewer;

#[tauri::command]
pub async fn start_pipeline(app: AppHandle, video_path: String, quality: Option<String>) -> Result<(), String> {
    config::load_env_fallback();
    let cli_path = cli::resolve_cli_path(&app)?;
    let ffmpeg_path = cli::resolve_bundled_tool_path(&app, "ffmpeg");

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

    let proxy_url = config::get_proxy_url();
    let proxy_token = config::get_proxy_auth_token();
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
    let last_stderr = Arc::new(std::sync::Mutex::new(String::new()));

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

        let maybe_child = child_handle.lock().unwrap().take();
        if let Some(mut child) = maybe_child {
            match child.wait().await {
                Ok(status) if !got_terminal => {
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
        }

        let _ = app_clone.emit("pipeline-exit", ());
    });

    Ok(())
}

fn parse_and_emit(app: &AppHandle, line: &str, last_non_json: &mut String) -> bool {
    let Ok(value) = serde_json::from_str::<serde_json::Value>(line) else {
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

#[tauri::command]
pub fn load_topics(project_dir: String) -> Result<Vec<TopicEntry>, String> {
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

#[tauri::command]
pub fn load_beats(project_dir: String) -> Result<BeatsResponse, String> {
    let base = std::path::Path::new(&project_dir);

    let beats_path = base.join("beats.json");
    if !beats_path.exists() {
        return Err(format!("beats.json not found in {project_dir}"));
    }

    let data = std::fs::read_to_string(&beats_path)
        .map_err(|e| format!("Failed to read beats.json: {e}"))?;
    let beats_file: BeatsFile = serde_json::from_str(&data)
        .map_err(|e| format!("Failed to parse beats.json: {e}"))?;

    let video_path = models::find_video_file(base);

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

#[tauri::command]
pub async fn start_viewer_server(app: AppHandle, project_dir: String) -> Result<u16, String> {
    let port_handle = app.state::<AppState>().viewer_server_port.clone();
    let shared_dir = app.state::<AppState>().viewer_project_dir.clone();

    *shared_dir.lock().unwrap() = project_dir.clone();

    if let Some(port) = *port_handle.lock().unwrap() {
        return Ok(port);
    }

    let state = ViewerServerState {
        project_dir: shared_dir.clone(),
    };

    let port = viewer::build_and_spawn(state).await?;

    *port_handle.lock().unwrap() = Some(port);

    Ok(port)
}

#[tauri::command]
pub fn cancel_pipeline(app: AppHandle) {
    if let Some(mut child) = app.state::<AppState>().child.lock().unwrap().take() {
        let _ = child.start_kill();
    }
}

#[tauri::command]
pub fn seed_demo_project() -> Result<bool, String> {
    let home = std::env::var("HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_default();
    let demo_dir = home.join(".videotool").join("projects").join("demo_sample");

    if demo_dir.join("beats.json").exists() {
        return Ok(false);
    }

    std::fs::create_dir_all(&demo_dir)
        .map_err(|e| format!("Failed to create demo dir: {e}"))?;

    let meta = include_str!("../demo/meta.json");
    let beats = include_str!("../demo/beats.json");

    std::fs::write(demo_dir.join("meta.json"), meta)
        .map_err(|e| format!("Failed to write demo meta: {e}"))?;
    std::fs::write(demo_dir.join("beats.json"), beats)
        .map_err(|e| format!("Failed to write demo beats: {e}"))?;

    Ok(true)
}

#[tauri::command]
pub fn list_projects() -> Result<Vec<ProjectInfo>, String> {
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

    results.sort_by(|a, b| b.created_at.cmp(&a.created_at));

    Ok(results)
}

#[cfg(test)]
mod tests {
    #[test]
    fn test_non_utf8_replacement_chars_ignored() {
        let garbage = "\u{FFFD}\u{FFFD}\u{FFFD}";
        let result = serde_json::from_str::<serde_json::Value>(garbage);
        assert!(result.is_err(), "garbage bytes should not parse as JSON");
    }

    #[test]
    fn test_malformed_json_ignored() {
        let cases = [
            "{step:1}",
            r#"{"step":1"#,
            r#"{"step":1,"total":5,"pct":}"#,
            "",
            "null",
        ];

        for input in &cases {
            let result = serde_json::from_str::<serde_json::Value>(input);
            match result {
                Err(_) => {}
                Ok(value) => {
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
