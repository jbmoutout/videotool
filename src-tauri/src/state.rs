use std::sync::{Arc, Mutex};
use tokio::process::Child;

pub(crate) type ChildHandle = Arc<Mutex<Option<Child>>>;

pub(crate) struct AppState {
    pub(crate) child: ChildHandle,
    pub(crate) viewer_server_port: Arc<Mutex<Option<u16>>>,
    pub(crate) viewer_project_dir: Arc<Mutex<String>>,
}

#[derive(Clone)]
pub(crate) struct ViewerServerState {
    pub(crate) project_dir: Arc<Mutex<String>>,
}
