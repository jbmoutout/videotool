use tauri::AppHandle;

pub fn resolve_cli_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
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

    if cfg!(debug_assertions) {
        let fallback = std::path::PathBuf::from("videotool");
        eprintln!("[videotool-app] resolved cli_path (PATH fallback) = {:?}", fallback);
        Ok(fallback)
    } else {
        Err("Bundled videotool binary not found (resource_dir unavailable)".to_string())
    }
}

pub fn resolve_bundled_tool_path(app: &AppHandle, base_name: &str) -> Option<std::path::PathBuf> {
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
