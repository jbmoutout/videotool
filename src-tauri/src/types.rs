use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ProgressMsg {
    pub step: u32,
    pub total: u32,
    pub pct: f64,
    pub msg: String,
    #[serde(default)]
    pub download_pct: Option<u32>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ErrorMsg {
    pub error: String,
    pub step: u32,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct DoneMsg {
    pub done: bool,
    pub project_dir: String,
    #[serde(default)]
    pub topic_count: u32,
    #[serde(default)]
    pub beat_count: u32,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct TopicEntry {
    pub topic_id: String,
    pub label: String,
    pub summary: String,
    pub duration_label: String,
    pub chunk_count: u32,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct BeatEntry {
    #[serde(rename = "type")]
    pub beat_type: String,
    pub start_s: f64,
    pub end_s: f64,
    pub confidence: f64,
    pub label: String,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct BeatTopic {
    pub topic_id: String,
    pub topic_label: String,
    pub beats: Vec<BeatEntry>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub(crate) struct BeatsFile {
    pub beats: Vec<BeatTopic>,
}

#[derive(Debug, Serialize, Clone)]
pub struct ProjectInfo {
    pub project_id: String,
    pub source_filename: String,
    pub title: Option<String>,
    pub channel: Option<String>,
    pub created_at: String,
    pub has_beats: bool,
    pub project_dir: String,
}

#[derive(Debug, Serialize, Clone)]
pub struct BeatsResponse {
    pub beats: Vec<BeatTopic>,
    pub video_path: Option<String>,
    pub duration_seconds: Option<f64>,
}
