use std::sync::{Arc, Mutex};
use tokio::process::Child;

pub type ChildHandle = Arc<Mutex<Option<Child>>>;

pub struct AppState {
    pub child: ChildHandle,
    pub viewer_server_port: Arc<Mutex<Option<u16>>>,
    pub viewer_project_dir: Arc<Mutex<String>>,
}

#[derive(Clone)]
pub struct ViewerServerState {
    pub project_dir: Arc<Mutex<String>>,
}
