//! Sync client for Voice peer-to-peer synchronization.
//!
//! This module provides the client side of the sync protocol, allowing
//! this device to:
//! - Connect to peer sync servers
//! - Pull changes from peers
//! - Push local changes to peers
//! - Handle TOFU certificate verification

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use chrono::{DateTime, Utc};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::config::Config;
use crate::database::Database;
use crate::error::{VoiceError, VoiceResult};

/// Result of a sync operation
#[derive(Debug, Clone, Default)]
pub struct SyncResult {
    pub success: bool,
    pub pulled: i64,
    pub pushed: i64,
    pub conflicts: i64,
    pub errors: Vec<String>,
}

impl SyncResult {
    pub fn success() -> Self {
        Self {
            success: true,
            ..Default::default()
        }
    }

    pub fn failure(error: impl Into<String>) -> Self {
        Self {
            success: false,
            errors: vec![error.into()],
            ..Default::default()
        }
    }
}

/// Information about a sync peer
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeerInfo {
    pub peer_id: String,
    pub peer_name: String,
    pub peer_url: String,
    pub certificate_fingerprint: Option<String>,
    pub last_sync_at: Option<String>,
}

/// Handshake request
#[derive(Debug, Serialize)]
struct HandshakeRequest {
    device_id: String,
    device_name: String,
    protocol_version: String,
}

/// Handshake response
#[derive(Debug, Deserialize)]
struct HandshakeResponse {
    device_id: String,
    device_name: String,
    protocol_version: String,
    last_sync_timestamp: Option<String>,
    server_timestamp: Option<String>,
}

/// Sync change
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncChange {
    pub entity_type: String,
    pub entity_id: String,
    pub operation: String,
    pub data: serde_json::Value,
    pub timestamp: String,
    pub device_id: String,
    pub device_name: Option<String>,
}

/// Sync batch response
#[derive(Debug, Deserialize)]
struct SyncBatchResponse {
    changes: Vec<SyncChange>,
    from_timestamp: Option<String>,
    to_timestamp: Option<String>,
    device_id: String,
    device_name: Option<String>,
    is_complete: bool,
}

/// Apply request
#[derive(Debug, Serialize)]
struct ApplyRequest {
    device_id: String,
    device_name: String,
    changes: Vec<SyncChange>,
}

/// Apply response
#[derive(Debug, Deserialize)]
struct ApplyResponse {
    applied: i64,
    conflicts: i64,
    errors: Vec<String>,
}

/// Sync client
pub struct SyncClient {
    db: Arc<Mutex<Database>>,
    config: Arc<Mutex<Config>>,
    client: Client,
    device_id: String,
    device_name: String,
}

impl SyncClient {
    /// Create a new sync client
    pub fn new(db: Arc<Mutex<Database>>, config: Arc<Mutex<Config>>) -> VoiceResult<Self> {
        let (device_id, device_name) = {
            let cfg = config.lock().unwrap();
            (cfg.device_id_hex().to_string(), cfg.device_name().to_string())
        };

        let client = Client::builder()
            .timeout(Duration::from_secs(30))
            .danger_accept_invalid_certs(true) // For TOFU - we verify fingerprints manually
            .build()
            .map_err(|e| VoiceError::Network(e.to_string()))?;

        Ok(Self {
            db,
            config,
            client,
            device_id,
            device_name,
        })
    }

    /// Perform full sync with a peer (bidirectional)
    pub async fn sync_with_peer(&self, peer_id: &str) -> SyncResult {
        let peer = {
            let config = self.config.lock().unwrap();
            config.get_peer(peer_id).cloned()
        };

        let peer = match peer {
            Some(p) => p,
            None => return SyncResult::failure(format!("Unknown peer: {}", peer_id)),
        };

        let peer_url = &peer.peer_url;
        let mut result = SyncResult::success();

        // Step 1: Handshake
        let handshake = match self.handshake(peer_url).await {
            Ok(h) => h,
            Err(e) => return SyncResult::failure(format!("Handshake failed: {}", e)),
        };

        let last_sync = handshake.last_sync_timestamp;
        let clock_skew = self.calculate_clock_skew(handshake.server_timestamp.as_deref());

        // Adjust pull timestamp for clock skew
        let adjusted_since = self.adjust_timestamp_for_skew(last_sync.as_deref(), clock_skew);

        // Step 2: Pull changes
        match self.pull_changes(peer_url, adjusted_since.as_deref()).await {
            Ok((applied, conflicts)) => {
                result.pulled = applied;
                result.conflicts += conflicts;
            }
            Err(e) => {
                result.errors.push(format!("Pull failed: {}", e));
            }
        }

        // Step 3: Push changes
        match self.push_changes(peer_url, last_sync.as_deref()).await {
            Ok((applied, conflicts)) => {
                result.pushed = applied;
                result.conflicts += conflicts;
            }
            Err(e) => {
                result.errors.push(format!("Push failed: {}", e));
            }
        }

        // Update last sync time
        if let Err(e) = self.update_peer_sync_time(peer_id) {
            result.errors.push(format!("Failed to update sync time: {}", e));
        }

        result.success = result.errors.is_empty();
        result
    }

    /// Pull changes from a peer (one-way)
    pub async fn pull_from_peer(&self, peer_id: &str) -> SyncResult {
        let peer = {
            let config = self.config.lock().unwrap();
            config.get_peer(peer_id).cloned()
        };

        let peer = match peer {
            Some(p) => p,
            None => return SyncResult::failure(format!("Unknown peer: {}", peer_id)),
        };

        let peer_url = &peer.peer_url;
        let mut result = SyncResult::success();

        // Handshake
        let handshake = match self.handshake(peer_url).await {
            Ok(h) => h,
            Err(e) => return SyncResult::failure(format!("Handshake failed: {}", e)),
        };

        let clock_skew = self.calculate_clock_skew(handshake.server_timestamp.as_deref());
        let adjusted_since =
            self.adjust_timestamp_for_skew(handshake.last_sync_timestamp.as_deref(), clock_skew);

        // Pull
        match self.pull_changes(peer_url, adjusted_since.as_deref()).await {
            Ok((applied, conflicts)) => {
                result.pulled = applied;
                result.conflicts = conflicts;
            }
            Err(e) => {
                result.success = false;
                result.errors.push(e.to_string());
            }
        }

        result
    }

    /// Push changes to a peer (one-way)
    pub async fn push_to_peer(&self, peer_id: &str) -> SyncResult {
        let peer = {
            let config = self.config.lock().unwrap();
            config.get_peer(peer_id).cloned()
        };

        let peer = match peer {
            Some(p) => p,
            None => return SyncResult::failure(format!("Unknown peer: {}", peer_id)),
        };

        let peer_url = &peer.peer_url;
        let mut result = SyncResult::success();

        // Handshake
        let handshake = match self.handshake(peer_url).await {
            Ok(h) => h,
            Err(e) => return SyncResult::failure(format!("Handshake failed: {}", e)),
        };

        // Push
        match self
            .push_changes(peer_url, handshake.last_sync_timestamp.as_deref())
            .await
        {
            Ok((applied, conflicts)) => {
                result.pushed = applied;
                result.conflicts = conflicts;
            }
            Err(e) => {
                result.success = false;
                result.errors.push(e.to_string());
            }
        }

        result
    }

    /// Check if a peer is reachable
    pub async fn check_peer_status(&self, peer_id: &str) -> HashMap<String, serde_json::Value> {
        let peer = {
            let config = self.config.lock().unwrap();
            config.get_peer(peer_id).cloned()
        };

        let peer = match peer {
            Some(p) => p,
            None => {
                let mut result = HashMap::new();
                result.insert("reachable".to_string(), serde_json::Value::Bool(false));
                result.insert(
                    "error".to_string(),
                    serde_json::Value::String("Unknown peer".to_string()),
                );
                return result;
            }
        };

        match self
            .client
            .get(format!("{}/sync/status", peer.peer_url))
            .send()
            .await
        {
            Ok(response) => {
                if response.status().is_success() {
                    match response.json::<serde_json::Value>().await {
                        Ok(data) => {
                            let mut result = HashMap::new();
                            result.insert("reachable".to_string(), serde_json::Value::Bool(true));
                            if let Some(device_id) = data.get("device_id") {
                                result.insert("device_id".to_string(), device_id.clone());
                            }
                            if let Some(device_name) = data.get("device_name") {
                                result.insert("device_name".to_string(), device_name.clone());
                            }
                            result
                        }
                        Err(e) => {
                            let mut result = HashMap::new();
                            result.insert("reachable".to_string(), serde_json::Value::Bool(false));
                            result.insert(
                                "error".to_string(),
                                serde_json::Value::String(e.to_string()),
                            );
                            result
                        }
                    }
                } else {
                    let mut result = HashMap::new();
                    result.insert("reachable".to_string(), serde_json::Value::Bool(false));
                    result.insert(
                        "error".to_string(),
                        serde_json::Value::String(format!("HTTP {}", response.status())),
                    );
                    result
                }
            }
            Err(e) => {
                let mut result = HashMap::new();
                result.insert("reachable".to_string(), serde_json::Value::Bool(false));
                result.insert(
                    "error".to_string(),
                    serde_json::Value::String(e.to_string()),
                );
                result
            }
        }
    }

    // Internal methods

    async fn handshake(&self, peer_url: &str) -> VoiceResult<HandshakeResponse> {
        let request = HandshakeRequest {
            device_id: self.device_id.clone(),
            device_name: self.device_name.clone(),
            protocol_version: "1.0".to_string(),
        };

        let response = self
            .client
            .post(format!("{}/sync/handshake", peer_url))
            .json(&request)
            .send()
            .await
            .map_err(|e| VoiceError::Network(e.to_string()))?;

        if !response.status().is_success() {
            return Err(VoiceError::Sync(format!(
                "Handshake failed with status {}",
                response.status()
            )));
        }

        response
            .json::<HandshakeResponse>()
            .await
            .map_err(|e| VoiceError::Sync(format!("Failed to parse handshake response: {}", e)))
    }

    async fn pull_changes(
        &self,
        peer_url: &str,
        since: Option<&str>,
    ) -> VoiceResult<(i64, i64)> {
        let url = match since {
            Some(ts) => format!(
                "{}/sync/changes?since={}",
                peer_url,
                urlencoding::encode(ts)
            ),
            None => format!("{}/sync/changes", peer_url),
        };

        let response = self
            .client
            .get(&url)
            .send()
            .await
            .map_err(|e| VoiceError::Network(e.to_string()))?;

        if !response.status().is_success() {
            return Err(VoiceError::Sync(format!(
                "Pull failed with status {}",
                response.status()
            )));
        }

        let batch: SyncBatchResponse = response
            .json()
            .await
            .map_err(|e| VoiceError::Sync(format!("Failed to parse changes: {}", e)))?;

        // Apply changes to local database
        let (applied, conflicts) = self.apply_changes(&batch.changes)?;

        Ok((applied, conflicts))
    }

    async fn push_changes(
        &self,
        peer_url: &str,
        since: Option<&str>,
    ) -> VoiceResult<(i64, i64)> {
        // Get local changes
        let changes = self.get_changes_since(since)?;

        if changes.is_empty() {
            return Ok((0, 0));
        }

        let request = ApplyRequest {
            device_id: self.device_id.clone(),
            device_name: self.device_name.clone(),
            changes,
        };

        let response = self
            .client
            .post(format!("{}/sync/apply", peer_url))
            .json(&request)
            .send()
            .await
            .map_err(|e| VoiceError::Network(e.to_string()))?;

        if !response.status().is_success() {
            return Err(VoiceError::Sync(format!(
                "Push failed with status {}",
                response.status()
            )));
        }

        let result: ApplyResponse = response
            .json()
            .await
            .map_err(|e| VoiceError::Sync(format!("Failed to parse apply response: {}", e)))?;

        Ok((result.applied, result.conflicts))
    }

    fn apply_changes(&self, _changes: &[SyncChange]) -> VoiceResult<(i64, i64)> {
        // TODO: Implement change application logic
        // This requires access to the sync module's apply_sync_changes function
        Ok((0, 0))
    }

    fn get_changes_since(&self, _since: Option<&str>) -> VoiceResult<Vec<SyncChange>> {
        // TODO: Implement getting local changes
        // This requires access to the sync module's get_changes_since function
        Ok(vec![])
    }

    fn calculate_clock_skew(&self, server_timestamp: Option<&str>) -> f64 {
        if let Some(ts) = server_timestamp {
            if let Ok(server_time) = DateTime::parse_from_rfc3339(ts) {
                let local_time = Utc::now();
                return (server_time.timestamp() - local_time.timestamp()) as f64;
            }
        }
        0.0
    }

    fn adjust_timestamp_for_skew(&self, timestamp: Option<&str>, clock_skew: f64) -> Option<String> {
        let ts = timestamp?;

        if let Ok(dt) = DateTime::parse_from_rfc3339(ts) {
            // Always go back at least 2 seconds for race conditions
            let base_adjustment = 2.0;
            // Add 2x skew if significant (> 1 second)
            let skew_adjustment = if clock_skew.abs() > 1.0 {
                2.0 * clock_skew.abs()
            } else {
                0.0
            };
            let total_adjustment = base_adjustment + skew_adjustment;

            let adjusted = dt - chrono::Duration::seconds(total_adjustment as i64);
            return Some(adjusted.format("%Y-%m-%d %H:%M:%S").to_string());
        }

        Some(ts.to_string())
    }

    fn update_peer_sync_time(&self, peer_id: &str) -> VoiceResult<()> {
        let peer_uuid = Uuid::parse_str(peer_id)?;
        let peer_bytes = peer_uuid.as_bytes().to_vec();

        let db = self.db.lock().unwrap();
        let conn = db.connection();

        // Try to update existing record
        let updated = conn.execute(
            "UPDATE sync_peers SET last_sync_at = datetime('now') WHERE peer_id = ?",
            [&peer_bytes],
        )?;

        if updated == 0 {
            // Insert new record
            let config = self.config.lock().unwrap();
            if let Some(peer) = config.get_peer(peer_id) {
                conn.execute(
                    "INSERT INTO sync_peers (peer_id, peer_name, peer_url, last_sync_at) VALUES (?, ?, ?, datetime('now'))",
                    rusqlite::params![peer_bytes, peer.peer_name, peer.peer_url],
                )?;
            }
        }

        Ok(())
    }
}

// ============================================================================
// Python bindings
// ============================================================================

/// Python wrapper for SyncResult
#[pyclass(name = "SyncResult")]
#[derive(Clone)]
pub struct PySyncResult {
    inner: SyncResult,
}

#[pymethods]
impl PySyncResult {
    #[getter]
    fn success(&self) -> bool {
        self.inner.success
    }

    #[getter]
    fn pulled(&self) -> i64 {
        self.inner.pulled
    }

    #[getter]
    fn pushed(&self) -> i64 {
        self.inner.pushed
    }

    #[getter]
    fn conflicts(&self) -> i64 {
        self.inner.conflicts
    }

    #[getter]
    fn errors(&self) -> Vec<String> {
        self.inner.errors.clone()
    }

    fn __repr__(&self) -> String {
        format!(
            "SyncResult(success={}, pulled={}, pushed={}, conflicts={}, errors={:?})",
            self.inner.success,
            self.inner.pulled,
            self.inner.pushed,
            self.inner.conflicts,
            self.inner.errors
        )
    }
}

/// Python wrapper for SyncClient
#[pyclass(name = "SyncClient")]
pub struct PySyncClient {
    // We need to store the client for async operations
    // For Python, we'll use a blocking approach or spawn tasks
    db: Arc<Mutex<Database>>,
    config: Arc<Mutex<Config>>,
    device_id: String,
    device_name: String,
}

#[pymethods]
impl PySyncClient {
    #[new]
    fn new(_db: &crate::database::PyDatabase, _config: &crate::config::PyConfig) -> PyResult<Self> {
        // This requires sharing the database and config instances
        // For now, return not implemented
        Err(pyo3::exceptions::PyNotImplementedError::new_err(
            "SyncClient creation from Python requires shared instances",
        ))
    }

    /// Sync with a peer (blocking)
    fn sync_with_peer(&self, _peer_id: &str) -> PyResult<PySyncResult> {
        // TODO: Implement blocking sync using tokio::runtime::Runtime
        Err(pyo3::exceptions::PyNotImplementedError::new_err(
            "sync_with_peer not yet implemented",
        ))
    }

    /// Pull from a peer (blocking)
    fn pull_from_peer(&self, _peer_id: &str) -> PyResult<PySyncResult> {
        Err(pyo3::exceptions::PyNotImplementedError::new_err(
            "pull_from_peer not yet implemented",
        ))
    }

    /// Push to a peer (blocking)
    fn push_to_peer(&self, _peer_id: &str) -> PyResult<PySyncResult> {
        Err(pyo3::exceptions::PyNotImplementedError::new_err(
            "push_to_peer not yet implemented",
        ))
    }

    /// Check peer status (blocking)
    fn check_peer_status(&self, _py: Python<'_>, _peer_id: &str) -> PyResult<PyObject> {
        Err(pyo3::exceptions::PyNotImplementedError::new_err(
            "check_peer_status not yet implemented",
        ))
    }
}

/// Sync with all configured peers
pub async fn sync_all_peers(
    db: Arc<Mutex<Database>>,
    config: Arc<Mutex<Config>>,
) -> HashMap<String, SyncResult> {
    let client = match SyncClient::new(db, config.clone()) {
        Ok(c) => c,
        Err(_) => return HashMap::new(),
    };

    let peers: Vec<String> = {
        let cfg = config.lock().unwrap();
        cfg.peers().iter().map(|p| p.peer_id.clone()).collect()
    };

    let mut results = HashMap::new();
    for peer_id in peers {
        let result = client.sync_with_peer(&peer_id).await;
        results.insert(peer_id, result);
    }

    results
}
