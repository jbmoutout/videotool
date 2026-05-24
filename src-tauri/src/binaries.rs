use std::path::PathBuf;
use tauri::AppHandle;

fn find_bundled_binary(
    dirs: &[PathBuf],
    base_name: &str,
    skip_name: Option<&str>,
) -> Option<PathBuf> {
    let arch = std::env::consts::ARCH;
    let mut candidates: Vec<(u32, PathBuf)> = Vec::new();
    let prefix_dash = format!("{base_name}-");
    let prefix_underscore = format!("{base_name}_");
    let exe_name = format!("{base_name}.exe");

    for dir in dirs {
        if let Ok(entries) = std::fs::read_dir(dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if !path.is_file() {
                    continue;
                }
                let name = entry.file_name().to_string_lossy().to_string();
                if skip_name.map_or(false, |skip| name == skip) {
                    continue;
                }

                let mut score = 0u32;
                if name == base_name || name == exe_name {
                    score += 100;
                }
                if name.contains(arch) {
                    score += 50;
                }
                if name.starts_with(&prefix_dash) || name.starts_with(&prefix_underscore) {
                    score += 10;
                }

                if score > 0 {
                    candidates.push((score, path));
                }
            }
        }
    }

    candidates.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
    candidates.into_iter().map(|(_, path)| path).next()
}

pub(crate) fn resolve_cli_path(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(resource_path) = app.path().resource_dir() {
        let mut searched_dirs = Vec::new();
        let mut skip_name: Option<String> = None;

        let mut extra_dir: Option<PathBuf> = None;
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

        for dir in &dirs {
            searched_dirs.push(dir.to_string_lossy().to_string());
        }

        if let Some(path) = find_bundled_binary(&dirs, "videotool", skip_name.as_deref()) {
            if cfg!(debug_assertions) {
                eprintln!("[videotool-app] resolved cli_path = {:?}", path);
            }
            return Ok(path);
        }

        if cfg!(debug_assertions) {
            let fallback = PathBuf::from("videotool");
            eprintln!("[videotool-app] resolved cli_path (PATH fallback) = {:?}", fallback);
            return Ok(fallback);
        }

        let expected = "videotool, videotool.exe, videotool-<target>, videotool_<target>";
        Err(format!(
            "Bundled videotool binary not found. Searched: {}. Expected one of: {}",
            searched_dirs.join(", "),
            expected
        ))
    } else {
        if cfg!(debug_assertions) {
            let fallback = PathBuf::from("videotool");
            eprintln!("[videotool-app] resolved cli_path (PATH fallback) = {:?}", fallback);
            Ok(fallback)
        } else {
            Err("Bundled videotool binary not found (resource_dir unavailable)".to_string())
        }
    }
}

pub(crate) fn resolve_bundled_tool_path(app: &AppHandle, base_name: &str) -> Option<PathBuf> {
    let mut dirs: Vec<PathBuf> = Vec::new();
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

    find_bundled_binary(&dirs, base_name, None)
}
