fn main() {
    tauri_build::build();
    // Rebuild when proxy config changes (read via option_env! at compile time).
    println!("cargo:rerun-if-env-changed=VITE_API_PROXY_URL");
    println!("cargo:rerun-if-env-changed=PROXY_AUTH_TOKEN");
}
