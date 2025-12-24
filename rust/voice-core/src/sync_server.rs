//! Sync server implementation using Axum.
//!
//! This module provides the server side of the sync protocol:
//! - /sync/handshake - Exchange device info
//! - /sync/changes - Get changes since timestamp
//! - /sync/apply - Apply changes from peer
//! - /sync/full - Get full dataset for initial sync
//! - /sync/status - Health check

use std::net::SocketAddr;
use std::sync::{Arc, Mutex, OnceLock};

use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use chrono::Utc;
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use tokio::sync::oneshot;
use uuid::Uuid;

use crate::config::Config;
use crate::database::Database;
use crate::error::VoiceResult;
use crate::sync_client::SyncChange;

/// Server shutdown handle
static SHUTDOWN_TX: OnceLock<Mutex<Option<oneshot::Sender<()>>>> = OnceLock::new();

/// Shared server state
#[derive(Clone)]
struct AppState {
    db: Arc<Mutex<Database>>,
    config: Arc<Mutex<Config>>,
    device_id: String,
    device_name: String,
}

// Request/Response types

#[derive(Debug, Deserialize)]
struct HandshakeRequest {
    device_id: String,
    device_name: String,
    protocol_version: String,
}

#[derive(Debug, Serialize)]
struct HandshakeResponse {
    device_id: String,
    device_name: String,
    protocol_version: String,
    last_sync_timestamp: Option<String>,
    server_timestamp: String,
}

#[derive(Debug, Deserialize)]
struct ChangesQuery {
    since: Option<String>,
    limit: Option<i64>,
}

#[derive(Debug, Serialize)]
struct ChangesResponse {
    changes: Vec<SyncChange>,
    from_timestamp: Option<String>,
    to_timestamp: Option<String>,
    device_id: String,
    device_name: String,
    is_complete: bool,
}

#[derive(Debug, Deserialize)]
struct ApplyRequest {
    device_id: String,
    device_name: String,
    changes: Vec<SyncChange>,
}

#[derive(Debug, Serialize)]
struct ApplyResponse {
    applied: i64,
    conflicts: i64,
    errors: Vec<String>,
}

#[derive(Debug, Serialize)]
struct StatusResponse {
    device_id: String,
    device_name: String,
    protocol_version: String,
    status: String,
}

#[derive(Debug, Serialize)]
struct ErrorResponse {
    error: String,
}

// Route handlers

async fn handshake(
    State(state): State<AppState>,
    Json(request): Json<HandshakeRequest>,
) -> impl IntoResponse {
    // Validate device_id
    if request.device_id.len() != 32 || !request.device_id.chars().all(|c| c.is_ascii_hexdigit()) {
        return (
            StatusCode::BAD_REQUEST,
            Json(ErrorResponse {
                error: "Invalid device_id format".to_string(),
            }),
        )
            .into_response();
    }

    // Get last sync timestamp for this peer
    let last_sync = get_peer_last_sync(&state.db, &request.device_id);

    let response = HandshakeResponse {
        device_id: state.device_id.clone(),
        device_name: state.device_name.clone(),
        protocol_version: "1.0".to_string(),
        last_sync_timestamp: last_sync,
        server_timestamp: Utc::now().to_rfc3339(),
    };

    Json(response).into_response()
}

async fn get_changes(
    State(state): State<AppState>,
    Query(query): Query<ChangesQuery>,
) -> impl IntoResponse {
    let limit = query.limit.unwrap_or(1000).min(10000);

    // Get changes from database
    let (changes, latest_timestamp) = match get_changes_since(&state.db, query.since.as_deref(), limit) {
        Ok(result) => result,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(ErrorResponse {
                    error: e.to_string(),
                }),
            )
                .into_response();
        }
    };

    let response = ChangesResponse {
        changes: changes.clone(),
        from_timestamp: query.since,
        to_timestamp: latest_timestamp,
        device_id: state.device_id.clone(),
        device_name: state.device_name.clone(),
        is_complete: (changes.len() as i64) < limit,
    };

    Json(response).into_response()
}

async fn apply_changes(
    State(state): State<AppState>,
    Json(request): Json<ApplyRequest>,
) -> impl IntoResponse {
    // Validate device_id
    if request.device_id.len() != 32 || !request.device_id.chars().all(|c| c.is_ascii_hexdigit()) {
        return (
            StatusCode::BAD_REQUEST,
            Json(ErrorResponse {
                error: "Invalid device_id format".to_string(),
            }),
        )
            .into_response();
    }

    // Apply changes
    let (applied, conflicts, errors) = match apply_sync_changes(
        &state.db,
        &request.changes,
        &request.device_id,
        Some(request.device_name.as_str()),
    ) {
        Ok(result) => result,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(ErrorResponse {
                    error: e.to_string(),
                }),
            )
                .into_response();
        }
    };

    let response = ApplyResponse {
        applied,
        conflicts,
        errors,
    };

    Json(response).into_response()
}

async fn get_full_sync(State(state): State<AppState>) -> impl IntoResponse {
    // Get all notes, tags, and note_tags
    let data = match get_full_dataset(&state.db) {
        Ok(d) => d,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(ErrorResponse {
                    error: e.to_string(),
                }),
            )
                .into_response();
        }
    };

    Json(data).into_response()
}

async fn status(State(state): State<AppState>) -> impl IntoResponse {
    Json(StatusResponse {
        device_id: state.device_id.clone(),
        device_name: state.device_name.clone(),
        protocol_version: "1.0".to_string(),
        status: "ok".to_string(),
    })
}

// Helper functions

fn get_peer_last_sync(db: &Arc<Mutex<Database>>, peer_id: &str) -> Option<String> {
    let peer_uuid = Uuid::parse_str(peer_id).ok()?;
    let peer_bytes = peer_uuid.as_bytes().to_vec();

    let db = db.lock().ok()?;
    let conn = db.connection();

    conn.query_row(
        "SELECT last_sync_at FROM sync_peers WHERE peer_id = ?",
        [peer_bytes],
        |row| row.get(0),
    )
    .ok()
}

fn get_changes_since(
    db: &Arc<Mutex<Database>>,
    since: Option<&str>,
    limit: i64,
) -> VoiceResult<(Vec<SyncChange>, Option<String>)> {
    let db = db.lock().unwrap();
    let conn = db.connection();

    let mut changes = Vec::new();
    let mut latest_timestamp: Option<String> = None;

    // Get notes changes
    let notes_query = if since.is_some() {
        "SELECT id, created_at, content, modified_at, deleted_at FROM notes \
         WHERE modified_at > ? OR (modified_at IS NULL AND created_at > ?) \
         ORDER BY COALESCE(modified_at, created_at) LIMIT ?"
    } else {
        "SELECT id, created_at, content, modified_at, deleted_at FROM notes \
         ORDER BY COALESCE(modified_at, created_at) LIMIT ?"
    };

    let mut stmt = conn.prepare(notes_query)?;
    let notes_rows: Vec<_> = if let Some(ts) = since {
        stmt.query_map(rusqlite::params![ts, ts, limit], |row| {
            let id_bytes: Vec<u8> = row.get(0)?;
            let created_at: String = row.get(1)?;
            let content: String = row.get(2)?;
            let modified_at: Option<String> = row.get(3)?;
            let deleted_at: Option<String> = row.get(4)?;

            Ok((id_bytes, created_at, content, modified_at, deleted_at))
        })?
        .collect()
    } else {
        stmt.query_map(rusqlite::params![limit], |row| {
            let id_bytes: Vec<u8> = row.get(0)?;
            let created_at: String = row.get(1)?;
            let content: String = row.get(2)?;
            let modified_at: Option<String> = row.get(3)?;
            let deleted_at: Option<String> = row.get(4)?;

            Ok((id_bytes, created_at, content, modified_at, deleted_at))
        })?
        .collect()
    };

    for row in notes_rows {
        let (id_bytes, created_at, content, modified_at, deleted_at) = row?;
        let id_hex = crate::validation::uuid_bytes_to_hex(&id_bytes)?;

        let operation = if deleted_at.is_some() {
            "delete"
        } else if modified_at.is_some() {
            "update"
        } else {
            "create"
        };

        let timestamp = modified_at
            .clone()
            .or_else(|| deleted_at.clone())
            .unwrap_or_else(|| created_at.clone());

        if latest_timestamp.is_none() || latest_timestamp.as_ref() < Some(&timestamp) {
            latest_timestamp = Some(timestamp.clone());
        }

        changes.push(SyncChange {
            entity_type: "note".to_string(),
            entity_id: id_hex.clone(),
            operation: operation.to_string(),
            data: serde_json::json!({
                "id": id_hex,
                "created_at": created_at,
                "content": content,
                "modified_at": modified_at,
                "deleted_at": deleted_at,
            }),
            timestamp,
            device_id: String::new(),
            device_name: None,
        });
    }

    // Similar queries for tags and note_tags would go here
    // Keeping this simplified for now

    Ok((changes, latest_timestamp))
}

fn apply_sync_changes(
    _db: &Arc<Mutex<Database>>,
    _changes: &[SyncChange],
    _peer_device_id: &str,
    _peer_device_name: Option<&str>,
) -> VoiceResult<(i64, i64, Vec<String>)> {
    // TODO: Implement full change application with conflict detection
    // This is a complex operation that needs careful implementation
    Ok((0, 0, vec![]))
}

fn get_full_dataset(db: &Arc<Mutex<Database>>) -> VoiceResult<serde_json::Value> {
    let db = db.lock().unwrap();
    let conn = db.connection();

    // Get all notes
    let mut notes = Vec::new();
    let mut stmt = conn.prepare(
        "SELECT id, created_at, content, modified_at, deleted_at FROM notes",
    )?;
    let note_rows = stmt.query_map([], |row| {
        let id_bytes: Vec<u8> = row.get(0)?;
        let created_at: String = row.get(1)?;
        let content: String = row.get(2)?;
        let modified_at: Option<String> = row.get(3)?;
        let deleted_at: Option<String> = row.get(4)?;
        Ok((id_bytes, created_at, content, modified_at, deleted_at))
    })?;

    for row in note_rows {
        let (id_bytes, created_at, content, modified_at, deleted_at) = row?;
        let id_hex = crate::validation::uuid_bytes_to_hex(&id_bytes)?;
        notes.push(serde_json::json!({
            "id": id_hex,
            "created_at": created_at,
            "content": content,
            "modified_at": modified_at,
            "deleted_at": deleted_at,
        }));
    }

    // Get all tags
    let mut tags = Vec::new();
    let mut stmt = conn.prepare(
        "SELECT id, name, parent_id, created_at, modified_at FROM tags",
    )?;
    let tag_rows = stmt.query_map([], |row| {
        let id_bytes: Vec<u8> = row.get(0)?;
        let name: String = row.get(1)?;
        let parent_id_bytes: Option<Vec<u8>> = row.get(2)?;
        let created_at: Option<String> = row.get(3)?;
        let modified_at: Option<String> = row.get(4)?;
        Ok((id_bytes, name, parent_id_bytes, created_at, modified_at))
    })?;

    for row in tag_rows {
        let (id_bytes, name, parent_id_bytes, created_at, modified_at) = row?;
        let id_hex = crate::validation::uuid_bytes_to_hex(&id_bytes)?;
        let parent_id_hex = parent_id_bytes
            .map(|b| crate::validation::uuid_bytes_to_hex(&b))
            .transpose()?;
        tags.push(serde_json::json!({
            "id": id_hex,
            "name": name,
            "parent_id": parent_id_hex,
            "created_at": created_at,
            "modified_at": modified_at,
        }));
    }

    // Get all note_tags
    let mut note_tags = Vec::new();
    let mut stmt = conn.prepare(
        "SELECT note_id, tag_id, created_at, modified_at, deleted_at FROM note_tags",
    )?;
    let note_tag_rows = stmt.query_map([], |row| {
        let note_id_bytes: Vec<u8> = row.get(0)?;
        let tag_id_bytes: Vec<u8> = row.get(1)?;
        let created_at: String = row.get(2)?;
        let modified_at: Option<String> = row.get(3)?;
        let deleted_at: Option<String> = row.get(4)?;
        Ok((note_id_bytes, tag_id_bytes, created_at, modified_at, deleted_at))
    })?;

    for row in note_tag_rows {
        let (note_id_bytes, tag_id_bytes, created_at, modified_at, deleted_at) = row?;
        let note_id_hex = crate::validation::uuid_bytes_to_hex(&note_id_bytes)?;
        let tag_id_hex = crate::validation::uuid_bytes_to_hex(&tag_id_bytes)?;
        note_tags.push(serde_json::json!({
            "note_id": note_id_hex,
            "tag_id": tag_id_hex,
            "created_at": created_at,
            "modified_at": modified_at,
            "deleted_at": deleted_at,
        }));
    }

    Ok(serde_json::json!({
        "notes": notes,
        "tags": tags,
        "note_tags": note_tags,
    }))
}

/// Create the sync server router
pub fn create_router(
    db: Arc<Mutex<Database>>,
    config: Arc<Mutex<Config>>,
) -> Router {
    let (device_id, device_name) = {
        let cfg = config.lock().unwrap();
        (cfg.device_id_hex().to_string(), cfg.device_name().to_string())
    };

    let state = AppState {
        db,
        config,
        device_id,
        device_name,
    };

    Router::new()
        .route("/sync/handshake", post(handshake))
        .route("/sync/changes", get(get_changes))
        .route("/sync/apply", post(apply_changes))
        .route("/sync/full", get(get_full_sync))
        .route("/sync/status", get(status))
        .with_state(state)
}

/// Start the sync server
pub async fn start_server(
    db: Arc<Mutex<Database>>,
    config: Arc<Mutex<Config>>,
    port: u16,
) -> VoiceResult<()> {
    let router = create_router(db, config);

    let addr = SocketAddr::from(([0, 0, 0, 0], port));

    // Create shutdown channel
    let (tx, rx) = oneshot::channel::<()>();
    SHUTDOWN_TX.get_or_init(|| Mutex::new(Some(tx)));

    tracing::info!("Starting sync server on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(|e| crate::error::VoiceError::Network(e.to_string()))?;

    axum::serve(listener, router)
        .with_graceful_shutdown(async {
            rx.await.ok();
        })
        .await
        .map_err(|e| crate::error::VoiceError::Network(e.to_string()))?;

    Ok(())
}

/// Stop the sync server
pub fn stop_server() {
    if let Some(mutex) = SHUTDOWN_TX.get() {
        if let Ok(mut guard) = mutex.lock() {
            if let Some(tx) = guard.take() {
                let _ = tx.send(());
            }
        }
    }
}

// ============================================================================
// Python bindings
// ============================================================================

/// Start sync server (spawns in background)
#[pyfunction]
#[pyo3(name = "start_sync_server")]
#[pyo3(signature = (_db, _config, _port=None))]
pub fn py_start_sync_server(
    _db: &crate::database::PyDatabase,
    _config: &crate::config::PyConfig,
    _port: Option<u16>,
) -> PyResult<()> {
    // TODO: This requires running tokio runtime in background
    Err(pyo3::exceptions::PyNotImplementedError::new_err(
        "start_sync_server not yet implemented for Python",
    ))
}

/// Stop sync server
#[pyfunction]
#[pyo3(name = "stop_sync_server")]
pub fn py_stop_sync_server() -> PyResult<()> {
    stop_server();
    Ok(())
}
