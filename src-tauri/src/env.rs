pub(crate) fn get_proxy_url() -> Option<String> {
    std::env::var("VITE_API_PROXY_URL")
        .ok()
        .or_else(|| option_env!("VITE_API_PROXY_URL").map(String::from))
        .filter(|s| !s.is_empty())
}

pub(crate) fn get_proxy_auth_token() -> Option<String> {
    std::env::var("PROXY_AUTH_TOKEN")
        .ok()
        .or_else(|| option_env!("PROXY_AUTH_TOKEN").map(String::from))
        .filter(|s| !s.is_empty())
}

pub(crate) fn load_env_fallback() {
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
