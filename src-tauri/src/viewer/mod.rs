mod range;
pub use range::parse_range;

use axum::body::Body;
use axum::extract::State as AxumState;
use axum::http::{HeaderMap, StatusCode};
use axum::response::IntoResponse;
use std::sync::Arc;
use tokio::io::{AsyncSeekExt, AsyncReadExt};
use tokio_util::io::ReaderStream;

use crate::models::{find_video_file, ViewerServerState};

pub const VIEWER_CSP: &str = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'";

const VIEWER_HTML: &str = include_str!("viewer.html");

pub async fn build_and_spawn(state: ViewerServerState) -> Result<u16, String> {
    let router = axum::Router::new()
        .route("/", axum::routing::get(serve_viewer_html))
        .route("/video", axum::routing::get(serve_video))
        .route("/beats.json", axum::routing::get(serve_beats_json))
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

    Ok(port)
}

async fn serve_viewer_html() -> impl IntoResponse {
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

async fn serve_beats_json(AxumState(state): AxumState<ViewerServerState>) -> impl IntoResponse {
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

    if let Some(range_header) = headers.get("range") {
        if let Ok(range_str) = range_header.to_str() {
            if let Some((start, end)) = parse_range(range_str, file_size) {
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
                    Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Response build failed").into_response(),
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

#[cfg(test)]
mod tests {
    use super::{serve_beats_json, serve_viewer_html, ViewerServerState, VIEWER_CSP};
    use axum::extract::State as AxumState;
    use axum::response::IntoResponse;
    use std::sync::{Arc, Mutex};

    fn test_runtime() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime")
    }

    #[test]
    fn test_serve_viewer_html_sets_security_headers() {
        let response = test_runtime().block_on(async { serve_viewer_html().await.into_response() });

        assert_eq!(response.status(), axum::http::StatusCode::OK);
        assert_eq!(
            response.headers().get("content-security-policy").unwrap(),
            VIEWER_CSP
        );
        assert_eq!(
            response.headers().get("cross-origin-resource-policy").unwrap(),
            "same-origin"
        );
        assert_eq!(response.headers().get("referrer-policy").unwrap(), "no-referrer");
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

        assert_eq!(response.status(), axum::http::StatusCode::OK);
        assert_eq!(response.headers().get("cache-control").unwrap(), "no-store");
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
