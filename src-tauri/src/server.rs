use axum::body::Body;
use axum::extract::State as AxumState;
use axum::http::{HeaderMap, StatusCode};
use axum::response::IntoResponse;
use std::sync::Arc;
use tokio::io::AsyncSeekExt;
use tokio_util::io::ReaderStream;

use crate::state::ViewerServerState;

const VIEWER_HTML: &str = include_str!("viewer.html");
const VIEWER_CSP: &str = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'";

pub fn find_video_file(base: &std::path::Path) -> Option<String> {
    let extensions = ["mp4", "mkv", "mov", "avi", "webm", "ts"];
    for ext in &extensions {
        let path = base.join(format!("source.{ext}"));
        if path.exists() {
            return Some(path.to_string_lossy().to_string());
        }
    }
    None
}

pub async fn serve_viewer_html() -> impl IntoResponse {
    (
        StatusCode::OK,
        [
            ("content-type", "text/html; charset=utf-8"),
            ("content-security-policy", VIEWER_CSP),
            ("cross-origin-resource-policy", "same-origin"),
            ("referrer-policy", "no-referrer"),
            ("x-content-type-options", "nosniff"),
        ],
        VIEWER_HTML,
    )
}

pub async fn serve_beats_json(
    AxumState(state): AxumState<ViewerServerState>,
) -> impl IntoResponse {
    let project_dir = state.project_dir.lock().unwrap().clone();
    let path = std::path::Path::new(&project_dir).join("beats.json");
    match tokio::fs::read_to_string(&path).await {
        Ok(data) => (
            StatusCode::OK,
            [
                ("content-type", "application/json"),
                ("cache-control", "no-store"),
                ("cross-origin-resource-policy", "same-origin"),
                ("x-content-type-options", "nosniff"),
            ],
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

pub async fn serve_video(
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
                    return (StatusCode::INTERNAL_SERVER_ERROR, "Seek failed").into_response();
                }

                let limited = file.take(length);
                let stream = ReaderStream::new(limited);
                let body = Body::from_stream(stream);

                let content_range = format!("bytes {start}-{end}/{file_size}");
                let len_str = length.to_string();

                return match axum::http::Response::builder()
                    .status(StatusCode::PARTIAL_CONTENT)
                    .header("content-type", content_type)
                    .header("accept-ranges", "bytes")
                    .header("cache-control", "no-store")
                    .header("content-range", content_range)
                    .header("content-length", len_str)
                    .header("cross-origin-resource-policy", "same-origin")
                    .header("x-content-type-options", "nosniff")
                    .body(body)
                {
                    Ok(resp) => resp.into_response(),
                    Err(_) => {
                        (StatusCode::INTERNAL_SERVER_ERROR, "Response build failed")
                            .into_response()
                    }
                };
            }
        }
    }

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
        .header("cache-control", "no-store")
        .header("content-length", len_str)
        .header("cross-origin-resource-policy", "same-origin")
        .header("x-content-type-options", "nosniff")
        .body(body)
    {
        Ok(resp) => resp.into_response(),
        Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Response build failed").into_response(),
    }
}

fn parse_range(range_str: &str, file_size: u64) -> Option<(u64, u64)> {
    if file_size == 0 {
        return None;
    }

    let range_str = range_str.strip_prefix("bytes=")?;
    let parts: Vec<&str> = range_str.splitn(2, '-').collect();
    if parts.len() != 2 {
        return None;
    }

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

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    fn test_runtime() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime")
    }

    #[test]
    fn test_parse_range_supports_standard_and_suffix_forms() {
        assert_eq!(parse_range("bytes=10-19", 100), Some((10, 19)));
        assert_eq!(parse_range("bytes=10-", 100), Some((10, 99)));
        assert_eq!(parse_range("bytes=-10", 100), Some((90, 99)));
        assert_eq!(parse_range("bytes=200-300", 100), None);
    }

    #[test]
    fn test_serve_viewer_html_sets_security_headers() {
        let response = test_runtime().block_on(async { serve_viewer_html().await.into_response() });

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers().get("content-security-policy").unwrap(),
            VIEWER_CSP
        );
        assert_eq!(
            response.headers().get("cross-origin-resource-policy").unwrap(),
            "same-origin"
        );
        assert_eq!(
            response.headers().get("referrer-policy").unwrap(),
            "no-referrer"
        );
        assert_eq!(
            response.headers().get("x-content-type-options").unwrap(),
            "nosniff"
        );
    }

    #[test]
    fn test_serve_beats_json_sets_no_store_and_same_origin_headers() {
        let temp_dir = std::env::temp_dir().join(format!(
            "videotool-beats-test-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        std::fs::write(temp_dir.join("beats.json"), r#"{"beats":[]}"#).expect("write beats");

        let state = ViewerServerState {
            project_dir: Arc::new(Mutex::new(temp_dir.to_string_lossy().to_string())),
        };

        let response = test_runtime().block_on(async {
            serve_beats_json(AxumState(state)).await.into_response()
        });

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers().get("cache-control").unwrap(),
            "no-store"
        );
        assert_eq!(
            response.headers().get("cross-origin-resource-policy").unwrap(),
            "same-origin"
        );
        assert_eq!(
            response.headers().get("x-content-type-options").unwrap(),
            "nosniff"
        );

        std::fs::remove_file(temp_dir.join("beats.json")).ok();
        std::fs::remove_dir(temp_dir).ok();
    }
}
