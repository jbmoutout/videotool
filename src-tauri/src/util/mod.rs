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
