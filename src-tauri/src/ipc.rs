use tauri::{AppHandle, Emitter};

use crate::types::{DoneMsg, ErrorMsg, ProgressMsg};

pub(crate) fn parse_and_emit(app: &AppHandle, line: &str, last_non_json: &mut String) -> bool {
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

#[cfg(test)]
mod tests {
    use super::*;

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
