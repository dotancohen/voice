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

    // Get tag changes
    let remaining = limit - changes.len() as i64;
    if remaining > 0 {
        let tags_query = if since.is_some() {
            "SELECT id, name, parent_id, created_at, modified_at FROM tags \
             WHERE modified_at > ? OR (modified_at IS NULL AND created_at > ?) \
             ORDER BY COALESCE(modified_at, created_at) LIMIT ?"
        } else {
            "SELECT id, name, parent_id, created_at, modified_at FROM tags \
             ORDER BY COALESCE(modified_at, created_at) LIMIT ?"
        };

        let mut stmt = conn.prepare(tags_query)?;
        let tag_rows: Vec<_> = if let Some(ts) = since {
            stmt.query_map(rusqlite::params![ts, ts, remaining], |row| {
                let id_bytes: Vec<u8> = row.get(0)?;
                let name: String = row.get(1)?;
                let parent_id_bytes: Option<Vec<u8>> = row.get(2)?;
                let created_at: String = row.get(3)?;
                let modified_at: Option<String> = row.get(4)?;
                Ok((id_bytes, name, parent_id_bytes, created_at, modified_at))
            })?
            .collect()
        } else {
            stmt.query_map(rusqlite::params![remaining], |row| {
                let id_bytes: Vec<u8> = row.get(0)?;
                let name: String = row.get(1)?;
                let parent_id_bytes: Option<Vec<u8>> = row.get(2)?;
                let created_at: String = row.get(3)?;
                let modified_at: Option<String> = row.get(4)?;
                Ok((id_bytes, name, parent_id_bytes, created_at, modified_at))
            })?
            .collect()
        };

        for row in tag_rows {
            let (id_bytes, name, parent_id_bytes, created_at, modified_at) = row?;
            let id_hex = crate::validation::uuid_bytes_to_hex(&id_bytes)?;
            let parent_id_hex = parent_id_bytes
                .map(|b| crate::validation::uuid_bytes_to_hex(&b))
                .transpose()?;

            let operation = if modified_at.is_some() { "update" } else { "create" };
            let timestamp = modified_at.clone().unwrap_or_else(|| created_at.clone());

            if latest_timestamp.is_none() || latest_timestamp.as_ref() < Some(&timestamp) {
                latest_timestamp = Some(timestamp.clone());
            }

            changes.push(SyncChange {
                entity_type: "tag".to_string(),
                entity_id: id_hex.clone(),
                operation: operation.to_string(),
                data: serde_json::json!({
                    "id": id_hex,
                    "name": name,
                    "parent_id": parent_id_hex,
                    "created_at": created_at,
                    "modified_at": modified_at,
                }),
                timestamp,
                device_id: String::new(),
                device_name: None,
            });
        }
    }

    // Get note_tag changes
    let remaining = limit - changes.len() as i64;
    if remaining > 0 {
        let note_tags_query = if since.is_some() {
            "SELECT note_id, tag_id, created_at, modified_at, deleted_at FROM note_tags \
             WHERE created_at > ? OR deleted_at > ? OR modified_at > ? \
             ORDER BY COALESCE(modified_at, deleted_at, created_at) LIMIT ?"
        } else {
            "SELECT note_id, tag_id, created_at, modified_at, deleted_at FROM note_tags \
             ORDER BY COALESCE(modified_at, deleted_at, created_at) LIMIT ?"
        };

        let mut stmt = conn.prepare(note_tags_query)?;
        let note_tag_rows: Vec<_> = if let Some(ts) = since {
            stmt.query_map(rusqlite::params![ts, ts, ts, remaining], |row| {
                let note_id_bytes: Vec<u8> = row.get(0)?;
                let tag_id_bytes: Vec<u8> = row.get(1)?;
                let created_at: String = row.get(2)?;
                let modified_at: Option<String> = row.get(3)?;
                let deleted_at: Option<String> = row.get(4)?;
                Ok((note_id_bytes, tag_id_bytes, created_at, modified_at, deleted_at))
            })?
            .collect()
        } else {
            stmt.query_map(rusqlite::params![remaining], |row| {
                let note_id_bytes: Vec<u8> = row.get(0)?;
                let tag_id_bytes: Vec<u8> = row.get(1)?;
                let created_at: String = row.get(2)?;
                let modified_at: Option<String> = row.get(3)?;
                let deleted_at: Option<String> = row.get(4)?;
                Ok((note_id_bytes, tag_id_bytes, created_at, modified_at, deleted_at))
            })?
            .collect()
        };

        for row in note_tag_rows {
            let (note_id_bytes, tag_id_bytes, created_at, modified_at, deleted_at) = row?;
            let note_id_hex = crate::validation::uuid_bytes_to_hex(&note_id_bytes)?;
            let tag_id_hex = crate::validation::uuid_bytes_to_hex(&tag_id_bytes)?;
            let entity_id = format!("{}:{}", note_id_hex, tag_id_hex);

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
                entity_type: "note_tag".to_string(),
                entity_id,
                operation: operation.to_string(),
                data: serde_json::json!({
                    "note_id": note_id_hex,
                    "tag_id": tag_id_hex,
                    "created_at": created_at,
                    "modified_at": modified_at,
                    "deleted_at": deleted_at,
                }),
                timestamp,
                device_id: String::new(),
                device_name: None,
            });
        }
    }

    Ok((changes, latest_timestamp))
}

fn apply_sync_changes(
    db: &Arc<Mutex<Database>>,
    changes: &[SyncChange],
    peer_device_id: &str,
    peer_device_name: Option<&str>,
) -> VoiceResult<(i64, i64, Vec<String>)> {
    let db = db.lock().unwrap();
    let mut applied = 0i64;
    let mut conflicts = 0i64;
    let mut errors = Vec::new();

    // Get last sync timestamp with this peer
    let last_sync_at = db.get_peer_last_sync(peer_device_id)?;

    for change in changes {
        let result = match change.entity_type.as_str() {
            "note" => apply_note_change(&db, change, last_sync_at.as_deref()),
            "tag" => apply_tag_change(&db, change, last_sync_at.as_deref()),
            "note_tag" => apply_note_tag_change(&db, change, last_sync_at.as_deref()),
            _ => {
                errors.push(format!("Unknown entity type: {}", change.entity_type));
                continue;
            }
        };

        match result {
            Ok(ApplyResult::Applied) => applied += 1,
            Ok(ApplyResult::Conflict) => conflicts += 1,
            Ok(ApplyResult::Skipped) => {}
            Err(e) => errors.push(format!(
                "Error applying {} {}: {}",
                change.entity_type, change.entity_id, e
            )),
        }
    }

    // Update peer's last sync timestamp
    db.update_peer_sync_time(peer_device_id, peer_device_name)?;

    Ok((applied, conflicts, errors))
}

enum ApplyResult {
    Applied,
    Conflict,
    Skipped,
}

fn apply_note_change(
    db: &Database,
    change: &SyncChange,
    last_sync_at: Option<&str>,
) -> VoiceResult<ApplyResult> {
    let note_id = &change.entity_id;
    let data = &change.data;

    let existing = db.get_note_raw(note_id)?;

    match change.operation.as_str() {
        "create" => {
            if existing.is_some() {
                return Ok(ApplyResult::Skipped);
            }
            db.apply_sync_note(
                note_id,
                data["created_at"].as_str().unwrap_or(""),
                data["content"].as_str().unwrap_or(""),
                data["modified_at"].as_str(),
                data["deleted_at"].as_str(),
            )?;
            Ok(ApplyResult::Applied)
        }
        "update" | "delete" => {
            let created_at = data["created_at"].as_str().unwrap_or("");
            let content = data["content"].as_str().unwrap_or("");
            let modified_at = data["modified_at"].as_str();
            let deleted_at = data["deleted_at"].as_str();

            if existing.is_none() {
                db.apply_sync_note(note_id, created_at, content, modified_at, deleted_at)?;
                return Ok(ApplyResult::Applied);
            }

            let existing = existing.unwrap();

            // Check if local changed since last sync
            let local_time = existing.get("modified_at")
                .and_then(|v| v.as_str())
                .or_else(|| existing.get("deleted_at").and_then(|v| v.as_str()));
            let local_changed = last_sync_at.is_none()
                || local_time.map_or(false, |lt| lt > last_sync_at.unwrap_or(""));

            // Determine timestamp of incoming change
            let incoming_time = modified_at.or(deleted_at);

            // If incoming change is before or at last_sync, skip
            if let (Some(last), Some(incoming)) = (last_sync_at, incoming_time) {
                if incoming <= last {
                    return Ok(ApplyResult::Skipped);
                }
            }

            if local_changed {
                // Both sides changed - for now, remote wins (could create conflict)
                // TODO: Implement proper conflict detection
            }

            db.apply_sync_note(note_id, created_at, content, modified_at, deleted_at)?;
            Ok(ApplyResult::Applied)
        }
        _ => Ok(ApplyResult::Skipped),
    }
}

fn apply_tag_change(
    db: &Database,
    change: &SyncChange,
    last_sync_at: Option<&str>,
) -> VoiceResult<ApplyResult> {
    let tag_id = &change.entity_id;
    let data = &change.data;

    let existing = db.get_tag_raw(tag_id)?;

    match change.operation.as_str() {
        "create" => {
            if existing.is_some() {
                return Ok(ApplyResult::Skipped);
            }
            db.apply_sync_tag(
                tag_id,
                data["name"].as_str().unwrap_or(""),
                data["parent_id"].as_str(),
                data["created_at"].as_str().unwrap_or(""),
                data["modified_at"].as_str(),
            )?;
            Ok(ApplyResult::Applied)
        }
        "update" => {
            let name = data["name"].as_str().unwrap_or("");
            let parent_id = data["parent_id"].as_str();
            let created_at = data["created_at"].as_str().unwrap_or("");
            let modified_at = data["modified_at"].as_str();

            if existing.is_none() {
                db.apply_sync_tag(tag_id, name, parent_id, created_at, modified_at)?;
                return Ok(ApplyResult::Applied);
            }

            // Check timestamp
            let incoming_time = modified_at;
            if let (Some(last), Some(incoming)) = (last_sync_at, incoming_time) {
                if incoming <= last {
                    return Ok(ApplyResult::Skipped);
                }
            }

            db.apply_sync_tag(tag_id, name, parent_id, created_at, modified_at)?;
            Ok(ApplyResult::Applied)
        }
        _ => Ok(ApplyResult::Skipped),
    }
}

fn apply_note_tag_change(
    db: &Database,
    change: &SyncChange,
    last_sync_at: Option<&str>,
) -> VoiceResult<ApplyResult> {
    // Parse entity_id (format: "note_id:tag_id")
    let parts: Vec<&str> = change.entity_id.split(':').collect();
    if parts.len() != 2 {
        return Ok(ApplyResult::Skipped);
    }

    let note_id = parts[0];
    let tag_id = parts[1];
    let data = &change.data;

    // Determine the timestamp of this incoming change
    let incoming_time = if change.operation == "delete" {
        data["deleted_at"].as_str().or_else(|| data["modified_at"].as_str())
    } else {
        data["modified_at"].as_str().or_else(|| data["created_at"].as_str())
    };

    // If this change happened before or at last_sync, skip it
    if let (Some(last), Some(incoming)) = (last_sync_at, incoming_time) {
        if incoming <= last {
            return Ok(ApplyResult::Skipped);
        }
    }

    let existing = db.get_note_tag_raw(note_id, tag_id)?;

    // Determine if local changed since last_sync
    let local_changed = if let Some(ref ex) = existing {
        let local_time = ex.get("modified_at")
            .and_then(|v| v.as_str())
            .or_else(|| ex.get("deleted_at").and_then(|v| v.as_str()))
            .or_else(|| ex.get("created_at").and_then(|v| v.as_str()));
        last_sync_at.is_none() || local_time.map_or(false, |lt| lt > last_sync_at.unwrap_or(""))
    } else {
        false
    };

    let created_at = data["created_at"].as_str().unwrap_or("");
    let modified_at = data["modified_at"].as_str();
    let deleted_at = data["deleted_at"].as_str();

    match change.operation.as_str() {
        "create" => {
            if let Some(ref ex) = existing {
                if ex.get("deleted_at").and_then(|v| v.as_str()).is_none() {
                    // Already active
                    return Ok(ApplyResult::Skipped);
                }
                // Local is deleted, remote wants active - reactivate
                let ex_created_at = ex.get("created_at").and_then(|v| v.as_str()).unwrap_or(created_at);
                db.apply_sync_note_tag(note_id, tag_id, ex_created_at, modified_at, None)?;
                return Ok(if local_changed { ApplyResult::Conflict } else { ApplyResult::Applied });
            }
            // New association
            db.apply_sync_note_tag(note_id, tag_id, created_at, modified_at, None)?;
            Ok(ApplyResult::Applied)
        }
        "delete" => {
            if existing.is_none() {
                // Create as deleted for sync consistency
                db.apply_sync_note_tag(note_id, tag_id, created_at, modified_at, deleted_at)?;
                return Ok(ApplyResult::Applied);
            }
            let ex = existing.unwrap();
            if ex.get("deleted_at").and_then(|v| v.as_str()).is_some() {
                return Ok(ApplyResult::Skipped); // Already deleted
            }
            // Local is active, remote wants to delete
            if local_changed {
                // Both changed - favor preservation (keep active)
                return Ok(ApplyResult::Conflict);
            }
            // Apply the delete
            let ex_created_at = ex.get("created_at").and_then(|v| v.as_str()).unwrap_or(created_at);
            db.apply_sync_note_tag(note_id, tag_id, ex_created_at, modified_at, deleted_at)?;
            Ok(ApplyResult::Applied)
        }
        "update" => {
            // Update operation - typically reactivation (deleted_at cleared)
            if existing.is_none() {
                db.apply_sync_note_tag(note_id, tag_id, created_at, modified_at, deleted_at)?;
                return Ok(ApplyResult::Applied);
            }

            let ex = existing.unwrap();
            let remote_deleted = deleted_at.is_some();
            let local_deleted = ex.get("deleted_at").and_then(|v| v.as_str()).is_some();
            let ex_created_at = ex.get("created_at").and_then(|v| v.as_str()).unwrap_or(created_at);

            if !remote_deleted && local_deleted {
                // Remote reactivated, local still deleted - reactivate
                db.apply_sync_note_tag(note_id, tag_id, ex_created_at, modified_at, None)?;
                return Ok(if local_changed { ApplyResult::Conflict } else { ApplyResult::Applied });
            }

            if remote_deleted && !local_deleted {
                // Remote wants to delete, local is active
                if local_changed {
                    return Ok(ApplyResult::Conflict); // Keep active
                }
                db.apply_sync_note_tag(note_id, tag_id, ex_created_at, modified_at, deleted_at)?;
                return Ok(ApplyResult::Applied);
            }

            // Both have same deleted state - update timestamps
            db.apply_sync_note_tag(note_id, tag_id, ex_created_at, modified_at, deleted_at)?;
            Ok(ApplyResult::Applied)
        }
        _ => Ok(ApplyResult::Skipped),
    }
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
