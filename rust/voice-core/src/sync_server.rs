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

#[derive(Debug, PartialEq)]
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
    let remote_device_id = &change.device_id;
    let remote_device_name = change.device_name.as_deref();

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
            let remote_content = data["content"].as_str().unwrap_or("");
            let modified_at = data["modified_at"].as_str();
            let deleted_at = data["deleted_at"].as_str();

            if existing.is_none() {
                db.apply_sync_note(note_id, created_at, remote_content, modified_at, deleted_at)?;
                return Ok(ApplyResult::Applied);
            }

            let existing = existing.unwrap();
            let local_content = existing.get("content")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let local_modified_at = existing.get("modified_at")
                .and_then(|v| v.as_str());
            let local_deleted_at = existing.get("deleted_at")
                .and_then(|v| v.as_str());

            // Check if local changed since last sync
            let local_time = local_modified_at.or(local_deleted_at);
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
                // Both sides changed - create appropriate conflict
                let local_deleted = local_deleted_at.is_some();
                let remote_deleted = deleted_at.is_some();

                if local_deleted && !remote_deleted {
                    // Local deleted, remote edited - create delete conflict
                    // The remote side has surviving content
                    db.create_note_delete_conflict(
                        note_id,
                        remote_content,                          // surviving_content
                        modified_at.unwrap_or(""),               // surviving_modified_at
                        Some(remote_device_id.as_str()),         // surviving_device_id
                        None,                                    // deleted_content
                        local_deleted_at.unwrap_or(""),          // deleted_at
                        None,                                    // deleting_device_id (local)
                        None,                                    // deleting_device_name
                    )?;
                    return Ok(ApplyResult::Conflict);
                } else if !local_deleted && remote_deleted {
                    // Local edited, remote deleted - create delete conflict
                    // The local side has surviving content
                    db.create_note_delete_conflict(
                        note_id,
                        local_content,                           // surviving_content
                        local_modified_at.unwrap_or(""),         // surviving_modified_at
                        None,                                    // surviving_device_id (local)
                        None,                                    // deleted_content
                        deleted_at.unwrap_or(""),                // deleted_at
                        Some(remote_device_id.as_str()),         // deleting_device_id
                        remote_device_name,                      // deleting_device_name
                    )?;
                    return Ok(ApplyResult::Conflict);
                } else if !local_deleted && !remote_deleted {
                    // Both edited - check if content is identical
                    if local_content == remote_content {
                        // Same content - no conflict needed, just apply to update timestamps
                        db.apply_sync_note(note_id, created_at, remote_content, modified_at, deleted_at)?;
                        return Ok(ApplyResult::Applied);
                    }
                    // Different content - create content conflict
                    db.create_note_content_conflict(
                        note_id,
                        local_content,
                        local_modified_at.unwrap_or(""),
                        remote_content,
                        modified_at.unwrap_or(""),
                        Some(remote_device_id.as_str()),
                        remote_device_name,
                    )?;
                    return Ok(ApplyResult::Conflict);
                }
                // Both deleted - no conflict, just apply
            }

            db.apply_sync_note(note_id, created_at, remote_content, modified_at, deleted_at)?;
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
    let remote_device_id = &change.device_id;
    let remote_device_name = change.device_name.as_deref();

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
            let remote_name = data["name"].as_str().unwrap_or("");
            let remote_parent_id = data["parent_id"].as_str();
            let created_at = data["created_at"].as_str().unwrap_or("");
            let modified_at = data["modified_at"].as_str();

            if existing.is_none() {
                db.apply_sync_tag(tag_id, remote_name, remote_parent_id, created_at, modified_at)?;
                return Ok(ApplyResult::Applied);
            }

            let existing = existing.unwrap();
            let local_name = existing.get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let local_parent_id = existing.get("parent_id")
                .and_then(|v| v.as_str());
            let local_modified_at = existing.get("modified_at")
                .and_then(|v| v.as_str());

            // Check if local changed since last sync
            let local_changed = last_sync_at.is_none()
                || local_modified_at.map_or(false, |lt| lt > last_sync_at.unwrap_or(""));

            // Check timestamp - skip if incoming is before last_sync
            if let (Some(last), Some(incoming)) = (last_sync_at, modified_at) {
                if incoming <= last {
                    return Ok(ApplyResult::Skipped);
                }
            }

            let mut has_conflict = false;

            // Check for name conflict
            if local_changed && local_name != remote_name {
                // Both renamed the tag differently - create rename conflict
                db.create_tag_rename_conflict(
                    tag_id,
                    local_name,
                    local_modified_at.unwrap_or(""),
                    remote_name,
                    modified_at.unwrap_or(""),
                    Some(remote_device_id.as_str()),
                    remote_device_name,
                )?;
                has_conflict = true;
            }

            // Check for parent_id conflict
            if local_changed && local_parent_id != remote_parent_id {
                // Both moved the tag to different parents - create parent conflict
                db.create_tag_parent_conflict(
                    tag_id,
                    local_parent_id,
                    local_modified_at.unwrap_or(""),
                    remote_parent_id,
                    modified_at.unwrap_or(""),
                    Some(remote_device_id.as_str()),
                    remote_device_name,
                )?;
                has_conflict = true;
            }

            if has_conflict {
                // Don't apply the remote change - keep local state
                return Ok(ApplyResult::Conflict);
            }

            db.apply_sync_tag(tag_id, remote_name, remote_parent_id, created_at, modified_at)?;
            Ok(ApplyResult::Applied)
        }
        "delete" => {
            // Tag deletion handling
            let deleted_at = data["deleted_at"].as_str()
                .or_else(|| data["modified_at"].as_str())
                .unwrap_or("");

            if existing.is_none() {
                // Tag doesn't exist locally - nothing to delete
                return Ok(ApplyResult::Skipped);
            }

            let existing = existing.unwrap();
            let local_name = existing.get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let local_parent_id = existing.get("parent_id")
                .and_then(|v| v.as_str());
            let local_modified_at = existing.get("modified_at")
                .and_then(|v| v.as_str());

            // Check if local changed since last sync
            let local_changed = last_sync_at.is_none()
                || local_modified_at.map_or(false, |lt| lt > last_sync_at.unwrap_or(""));

            if local_changed {
                // Local modified the tag, but remote wants to delete
                // Create a delete conflict - preserve the local version
                db.create_tag_delete_conflict(
                    tag_id,
                    local_name,                          // surviving_name
                    local_parent_id,                     // surviving_parent_id
                    local_modified_at.unwrap_or(""),     // surviving_modified_at
                    None,                                // surviving_device_id (local)
                    None,                                // surviving_device_name
                    deleted_at,                          // deleted_at
                    Some(remote_device_id.as_str()),     // deleting_device_id
                    remote_device_name,                  // deleting_device_name
                )?;
                return Ok(ApplyResult::Conflict);
            }

            // No local changes - safe to delete
            // Note: This is a hard delete since tags don't have soft delete
            db.delete_tag(tag_id)?;
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

// ============================================================================
// Tests - CRITICAL: Verify zero data loss in sync
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};
    use tempfile::TempDir;
    use uuid::Uuid;

    /// Create a test database in a temporary directory
    fn create_test_db() -> (Database, TempDir) {
        let temp_dir = TempDir::new().unwrap();
        let db_path = temp_dir.path().join("test.db");
        let db = Database::new(db_path.to_str().unwrap()).unwrap();
        (db, temp_dir)
    }

    /// Create a SyncChange for testing
    fn make_sync_change(
        entity_type: &str,
        entity_id: &str,
        operation: &str,
        data: serde_json::Value,
        device_id: &str,
    ) -> SyncChange {
        let timestamp = data.get("modified_at")
            .or_else(|| data.get("deleted_at"))
            .or_else(|| data.get("created_at"))
            .and_then(|v| v.as_str())
            .unwrap_or("2025-01-01 00:00:00")
            .to_string();

        SyncChange {
            entity_type: entity_type.to_string(),
            entity_id: entity_id.to_string(),
            operation: operation.to_string(),
            data,
            timestamp,
            device_id: device_id.to_string(),
            device_name: Some("Remote Device".to_string()),
        }
    }

    // =========================================================================
    // NOTE CONTENT CONFLICT TESTS
    // =========================================================================

    #[test]
    fn test_both_devices_edit_same_note_creates_conflict() {
        // CRITICAL: When both devices edit the same note, we MUST create a conflict.
        // We must NEVER silently overwrite one version with another.
        let (db, _temp) = create_test_db();

        // Create a note locally
        let note_id = db.create_note("Original content").unwrap();

        // Simulate local edit after initial sync
        db.update_note(&note_id, "Local edited content").unwrap();

        // Now receive a remote edit to the same note
        let remote_change = make_sync_change(
            "note",
            &note_id,
            "update",
            serde_json::json!({
                "id": note_id,
                "created_at": "2025-01-01 00:00:00",
                "content": "Remote edited content",
                "modified_at": "2025-01-01 12:00:00",
                "deleted_at": null,
            }),
            "00000000000070008000000000000099",
        );

        // Apply with no last_sync (meaning local changed since last sync)
        let result = apply_note_change(&db, &remote_change, None).unwrap();

        // MUST be a conflict, NOT applied
        assert_eq!(result, ApplyResult::Conflict,
            "CRITICAL: Both devices edited same note - MUST create conflict, not overwrite!");

        // Verify local content was NOT overwritten
        let note = db.get_note(&note_id).unwrap().unwrap();
        assert_eq!(note.content.as_str(), "Local edited content",
            "CRITICAL: Local content was overwritten! Data loss occurred!");

        // Verify a conflict record was created
        let conflicts = db.get_note_content_conflicts(false).unwrap();
        assert!(!conflicts.is_empty(),
            "CRITICAL: No conflict record created! User cannot resolve the conflict!");
    }

    #[test]
    fn test_remote_edit_after_sync_applies_cleanly() {
        // When only remote changed (local unchanged since last sync), apply cleanly
        let (db, _temp) = create_test_db();

        // Create a note
        let note_id = db.create_note("Original content").unwrap();

        // Receive remote edit with timestamp after last_sync
        let remote_change = make_sync_change(
            "note",
            &note_id,
            "update",
            serde_json::json!({
                "id": note_id,
                "created_at": "2025-01-01 00:00:00",
                "content": "Remote edited content",
                "modified_at": "2025-01-01 12:00:00",
                "deleted_at": null,
            }),
            "00000000000070008000000000000099",
        );

        // Apply with last_sync before the remote change (local unchanged)
        let result = apply_note_change(&db, &remote_change, Some("2025-01-01 06:00:00")).unwrap();

        // Should apply cleanly
        assert_eq!(result, ApplyResult::Applied);

        // Content should be updated
        let note = db.get_note(&note_id).unwrap().unwrap();
        assert_eq!(note.content.as_str(), "Remote edited content");
    }

    // =========================================================================
    // NOTE DELETE CONFLICT TESTS
    // =========================================================================

    #[test]
    fn test_local_edit_remote_delete_creates_conflict() {
        // CRITICAL: If local edited but remote deleted, MUST create conflict.
        // We cannot lose the local edits!
        let (db, _temp) = create_test_db();

        // Create a note
        let note_id = db.create_note("Original content").unwrap();

        // Local edits the note
        db.update_note(&note_id, "Important local edits").unwrap();

        // Remote tries to delete
        let remote_change = make_sync_change(
            "note",
            &note_id,
            "delete",
            serde_json::json!({
                "id": note_id,
                "created_at": "2025-01-01 00:00:00",
                "content": "Original content",
                "modified_at": null,
                "deleted_at": "2025-01-01 12:00:00",
            }),
            "00000000000070008000000000000099",
        );

        let result = apply_note_change(&db, &remote_change, None).unwrap();

        // MUST be a conflict
        assert_eq!(result, ApplyResult::Conflict,
            "CRITICAL: Local edited, remote deleted - MUST create conflict!");

        // Verify note was NOT deleted
        let note = db.get_note(&note_id).unwrap();
        assert!(note.is_some(), "CRITICAL: Note was deleted! Local edits lost!");
        assert_eq!(note.unwrap().content.as_str(), "Important local edits",
            "CRITICAL: Local edits were lost!");

        // Verify conflict record exists
        let conflicts = db.get_note_delete_conflicts(false).unwrap();
        assert!(!conflicts.is_empty(),
            "CRITICAL: No delete conflict record! User cannot resolve!");
    }

    #[test]
    fn test_local_delete_remote_edit_creates_conflict() {
        // CRITICAL: If local deleted but remote has edits, MUST create conflict.
        // The remote edits must not be lost!
        let (db, _temp) = create_test_db();

        // Create and delete a note locally
        let note_id = db.create_note("Original content").unwrap();
        db.delete_note(&note_id).unwrap();

        // Remote sends an edit (they didn't know it was deleted)
        let remote_change = make_sync_change(
            "note",
            &note_id,
            "update",
            serde_json::json!({
                "id": note_id,
                "created_at": "2025-01-01 00:00:00",
                "content": "Remote made important edits",
                "modified_at": "2025-01-01 12:00:00",
                "deleted_at": null,
            }),
            "00000000000070008000000000000099",
        );

        let result = apply_note_change(&db, &remote_change, None).unwrap();

        // MUST be a conflict
        assert_eq!(result, ApplyResult::Conflict,
            "CRITICAL: Local deleted, remote edited - MUST create conflict!");

        // Verify conflict record exists with surviving content
        let conflicts = db.get_note_delete_conflicts(false).unwrap();
        assert!(!conflicts.is_empty(),
            "CRITICAL: No delete conflict record! Remote edits could be lost!");
    }

    #[test]
    fn test_both_delete_same_note_no_conflict() {
        // When both sides delete, no conflict needed - they agree
        let (db, _temp) = create_test_db();

        // Create and delete locally
        let note_id = db.create_note("To be deleted").unwrap();
        db.delete_note(&note_id).unwrap();

        // Remote also deletes
        let remote_change = make_sync_change(
            "note",
            &note_id,
            "delete",
            serde_json::json!({
                "id": note_id,
                "created_at": "2025-01-01 00:00:00",
                "content": "To be deleted",
                "modified_at": null,
                "deleted_at": "2025-01-01 12:00:00",
            }),
            "00000000000070008000000000000099",
        );

        let result = apply_note_change(&db, &remote_change, None).unwrap();

        // Should apply (both agree on deletion)
        assert_eq!(result, ApplyResult::Applied);
    }

    // =========================================================================
    // TAG RENAME CONFLICT TESTS
    // =========================================================================

    #[test]
    fn test_both_devices_rename_tag_creates_conflict() {
        // CRITICAL: When both devices rename the same tag differently,
        // we MUST create a conflict. Cannot lose either name.
        let (db, _temp) = create_test_db();

        // Create a tag
        let tag_id = db.create_tag("original_name", None).unwrap();

        // Local renames it
        db.rename_tag(&tag_id, "local_renamed").unwrap();

        // Remote tries to rename differently
        let remote_change = make_sync_change(
            "tag",
            &tag_id,
            "update",
            serde_json::json!({
                "id": tag_id,
                "name": "remote_renamed",
                "parent_id": null,
                "created_at": "2025-01-01 00:00:00",
                "modified_at": "2025-01-01 12:00:00",
            }),
            "00000000000070008000000000000099",
        );

        let result = apply_tag_change(&db, &remote_change, None).unwrap();

        // MUST be a conflict
        assert_eq!(result, ApplyResult::Conflict,
            "CRITICAL: Both renamed tag differently - MUST create conflict!");

        // Verify local name was NOT overwritten
        let tags = db.get_all_tags().unwrap();
        let tag = tags.iter().find(|t| t.id == tag_id).unwrap();
        assert_eq!(tag.name.as_str(), "local_renamed",
            "CRITICAL: Local tag name was overwritten! Data loss!");

        // Verify conflict record exists
        let conflicts = db.get_tag_rename_conflicts(false).unwrap();
        assert!(!conflicts.is_empty(),
            "CRITICAL: No rename conflict record! User cannot choose!");
    }

    #[test]
    fn test_both_rename_tag_same_name_no_conflict() {
        // When both sides rename to the SAME name, no conflict
        let (db, _temp) = create_test_db();

        let tag_id = db.create_tag("original", None).unwrap();
        db.rename_tag(&tag_id, "agreed_name").unwrap();

        let remote_change = make_sync_change(
            "tag",
            &tag_id,
            "update",
            serde_json::json!({
                "id": tag_id,
                "name": "agreed_name",  // Same name!
                "parent_id": null,
                "created_at": "2025-01-01 00:00:00",
                "modified_at": "2025-01-01 12:00:00",
            }),
            "00000000000070008000000000000099",
        );

        let result = apply_tag_change(&db, &remote_change, None).unwrap();

        // Should apply cleanly - they agree
        assert_eq!(result, ApplyResult::Applied);
    }

    // =========================================================================
    // NOTE_TAG CONFLICT TESTS
    // =========================================================================

    #[test]
    fn test_note_tag_reactivation_applies() {
        // When remote reactivates a deleted note_tag that was deleted BEFORE last_sync,
        // it should apply (no local changes since last_sync)
        let (db, _temp) = create_test_db();

        let note_id = db.create_note("Test note").unwrap();
        let tag_id = db.create_tag("test_tag", None).unwrap();

        // Add and remove tag locally
        db.add_tag_to_note(&note_id, &tag_id).unwrap();
        db.remove_tag_from_note(&note_id, &tag_id).unwrap();

        // Remote reactivates (update with deleted_at=null)
        let entity_id = format!("{}:{}", note_id, tag_id);
        let remote_change = make_sync_change(
            "note_tag",
            &entity_id,
            "update",
            serde_json::json!({
                "note_id": note_id,
                "tag_id": tag_id,
                "created_at": "2025-01-01 00:00:00",
                "modified_at": "2099-01-01 12:00:00",  // Future time for the reactivation
                "deleted_at": null,  // Reactivated!
            }),
            "00000000000070008000000000000099",
        );

        // Use a far-future last_sync so local operations are considered "before last_sync"
        // This simulates: local deleted before last sync, then remote reactivates
        let result = apply_note_tag_change(&db, &remote_change, Some("2099-01-01 00:00:00")).unwrap();

        // Should apply since local hasn't changed since last_sync
        assert_eq!(result, ApplyResult::Applied);
    }

    // =========================================================================
    // COMPREHENSIVE DATA LOSS PREVENTION TESTS
    // =========================================================================

    #[test]
    fn test_no_silent_overwrites_ever() {
        // This test verifies the core invariant: we NEVER silently overwrite data.
        // Every conflict scenario must either:
        // 1. Create a conflict record, OR
        // 2. Be a case where both sides agree (same content, both deleted, etc.)

        let (db, _temp) = create_test_db();

        // Create test data
        let note_id = db.create_note("Important data").unwrap();

        // Edit locally
        db.update_note(&note_id, "My precious local edits").unwrap();

        let original_content = db.get_note(&note_id).unwrap().unwrap().content.clone();

        // Try to overwrite with remote data
        let remote_change = make_sync_change(
            "note",
            &note_id,
            "update",
            serde_json::json!({
                "id": note_id,
                "created_at": "2025-01-01 00:00:00",
                "content": "Remote trying to overwrite",
                "modified_at": "2025-01-01 12:00:00",
                "deleted_at": null,
            }),
            "00000000000070008000000000000099",
        );

        // Apply with no last_sync (local changed)
        let _result = apply_note_change(&db, &remote_change, None).unwrap();

        // VERIFY: Content MUST still be the local version
        let after = db.get_note(&note_id).unwrap().unwrap();
        let after_content = &after.content;

        assert_eq!(after_content, &original_content,
            "CRITICAL DATA LOSS: Content was overwritten!\n\
             Before: {}\n\
             After: {}\n\
             This is unacceptable - user data was silently lost!",
            original_content, after_content);
    }

    #[test]
    fn test_conflict_records_are_queryable() {
        // Users MUST be able to find and resolve conflicts
        let (db, _temp) = create_test_db();

        // Create a conflict scenario
        let note_id = db.create_note("Original").unwrap();
        db.update_note(&note_id, "Local edit").unwrap();

        let remote_change = make_sync_change(
            "note",
            &note_id,
            "update",
            serde_json::json!({
                "id": note_id,
                "created_at": "2025-01-01 00:00:00",
                "content": "Remote edit",
                "modified_at": "2025-01-01 12:00:00",
                "deleted_at": null,
            }),
            "00000000000070008000000000000099",
        );

        apply_note_change(&db, &remote_change, None).unwrap();

        // MUST be able to query unresolved conflicts
        let conflicts = db.get_note_content_conflicts(false).unwrap();
        assert!(!conflicts.is_empty(), "Conflicts must be queryable!");

        // Conflict must have both versions
        let conflict = &conflicts[0];
        let local_content = conflict.get("local_content").and_then(|v| v.as_str()).unwrap_or("");
        let remote_content = conflict.get("remote_content").and_then(|v| v.as_str()).unwrap_or("");
        assert!(!local_content.is_empty(), "Conflict must have local content!");
        assert!(!remote_content.is_empty(), "Conflict must have remote content!");
    }

    #[test]
    fn test_old_remote_changes_are_skipped() {
        // Changes from before last_sync should be skipped
        let (db, _temp) = create_test_db();

        let note_id = db.create_note("Current content").unwrap();

        // Remote sends old change (before last_sync)
        let remote_change = make_sync_change(
            "note",
            &note_id,
            "update",
            serde_json::json!({
                "id": note_id,
                "created_at": "2025-01-01 00:00:00",
                "content": "Old remote content",
                "modified_at": "2025-01-01 06:00:00",  // Before last_sync
                "deleted_at": null,
            }),
            "00000000000070008000000000000099",
        );

        // last_sync is AFTER the remote change
        let result = apply_note_change(&db, &remote_change, Some("2025-01-01 12:00:00")).unwrap();

        assert_eq!(result, ApplyResult::Skipped, "Old changes should be skipped");

        // Content unchanged
        let note = db.get_note(&note_id).unwrap().unwrap();
        assert_eq!(note.content.as_str(), "Current content");
    }

    #[test]
    fn test_apply_sync_changes_counts_conflicts_correctly() {
        // The apply_sync_changes function must accurately report conflicts
        let (db, _temp) = create_test_db();
        let db = Arc::new(Mutex::new(db));

        // Create notes and edit them locally
        let note1_id;
        let note2_id;
        {
            let db = db.lock().unwrap();
            note1_id = db.create_note("Note 1 local").unwrap();
            note2_id = db.create_note("Note 2 local").unwrap();
            db.update_note(&note1_id, "Note 1 local edited").unwrap();
            db.update_note(&note2_id, "Note 2 local edited").unwrap();
        }

        // Send remote edits for both
        let changes = vec![
            make_sync_change(
                "note",
                &note1_id,
                "update",
                serde_json::json!({
                    "id": note1_id,
                    "created_at": "2025-01-01 00:00:00",
                    "content": "Note 1 remote edit",
                    "modified_at": "2025-01-01 12:00:00",
                    "deleted_at": null,
                }),
                "00000000000070008000000000000099",
            ),
            make_sync_change(
                "note",
                &note2_id,
                "update",
                serde_json::json!({
                    "id": note2_id,
                    "created_at": "2025-01-01 00:00:00",
                    "content": "Note 2 remote edit",
                    "modified_at": "2025-01-01 12:00:00",
                    "deleted_at": null,
                }),
                "00000000000070008000000000000099",
            ),
        ];

        let (applied, conflicts, errors) = apply_sync_changes(
            &db,
            &changes,
            "00000000000070008000000000000099",
            Some("Remote"),
        ).unwrap();

        // Both should be conflicts
        assert_eq!(conflicts, 2, "Expected 2 conflicts!");
        assert_eq!(applied, 0, "No changes should be applied - all conflicts!");
        assert!(errors.is_empty(), "Should be no errors");
    }

    // =========================================================================
    // P0: TAG PARENT_ID CONFLICT TESTS
    // =========================================================================

    #[test]
    fn test_both_devices_move_tag_to_different_parents_creates_conflict() {
        // CRITICAL P0: When both devices move a tag to different parents,
        // we MUST create a conflict. Cannot silently lose either parent choice.
        let (db, _temp) = create_test_db();

        // Create parent tags and a child tag
        let parent_a = db.create_tag("parent_a", None).unwrap();
        let parent_b = db.create_tag("parent_b", None).unwrap();
        let child_tag = db.create_tag("child", None).unwrap();

        // Local moves child to parent_a
        db.apply_sync_tag(&child_tag, "child", Some(&parent_a), "", Some("2025-12-24 10:00:00")).unwrap();

        // Remote tries to move child to parent_b
        let remote_change = make_sync_change(
            "tag",
            &child_tag,
            "update",
            serde_json::json!({
                "id": child_tag,
                "name": "child",
                "parent_id": parent_b,
                "created_at": "2025-01-01 00:00:00",
                "modified_at": "2025-01-01 12:00:00",
            }),
            "00000000000070008000000000000099",
        );

        let result = apply_tag_change(&db, &remote_change, None).unwrap();

        // MUST be a conflict
        assert_eq!(result, ApplyResult::Conflict,
            "CRITICAL P0: Both moved tag to different parents - MUST create conflict!");

        // Verify parent_a was NOT overwritten (local wins, conflict recorded)
        let tags = db.get_all_tags().unwrap();
        let tag = tags.iter().find(|t| t.id == child_tag).unwrap();
        assert_eq!(tag.parent_id.as_deref(), Some(parent_a.as_str()),
            "CRITICAL P0: Local parent choice was overwritten! Data loss!");

        // Verify conflict record exists
        let conflicts = db.get_tag_parent_conflicts(false).unwrap();
        assert!(!conflicts.is_empty(),
            "CRITICAL P0: No parent conflict record! User cannot choose!");
    }

    #[test]
    fn test_both_move_tag_to_same_parent_no_conflict() {
        // When both devices move tag to the SAME parent, no conflict needed
        let (db, _temp) = create_test_db();

        let parent = db.create_tag("parent", None).unwrap();
        let child = db.create_tag("child", None).unwrap();

        // Local moves to parent
        db.apply_sync_tag(&child, "child", Some(&parent), "", Some("2025-12-24 10:00:00")).unwrap();

        // Remote also moves to same parent
        let remote_change = make_sync_change(
            "tag",
            &child,
            "update",
            serde_json::json!({
                "id": child,
                "name": "child",
                "parent_id": parent,
                "created_at": "2025-01-01 00:00:00",
                "modified_at": "2025-01-01 12:00:00",
            }),
            "00000000000070008000000000000099",
        );

        let result = apply_tag_change(&db, &remote_change, None).unwrap();

        // Should apply - they agree
        assert_eq!(result, ApplyResult::Applied);
    }

    // =========================================================================
    // P0: TAG DELETION CONFLICT TESTS
    // =========================================================================

    #[test]
    fn test_local_renames_tag_remote_deletes_creates_conflict() {
        // CRITICAL P0: If local renamed but remote deleted,
        // we MUST create conflict - cannot lose the rename.
        let (db, _temp) = create_test_db();

        let tag_id = db.create_tag("original", None).unwrap();

        // Local renames
        db.rename_tag(&tag_id, "renamed_locally").unwrap();

        // Remote tries to delete
        let remote_change = make_sync_change(
            "tag",
            &tag_id,
            "delete",
            serde_json::json!({
                "id": tag_id,
                "deleted_at": "2025-01-01 12:00:00",
            }),
            "00000000000070008000000000000099",
        );

        let result = apply_tag_change(&db, &remote_change, None).unwrap();

        // MUST be a conflict
        assert_eq!(result, ApplyResult::Conflict,
            "CRITICAL P0: Local renamed, remote deleted - MUST create conflict!");

        // Verify tag was NOT deleted
        let tags = db.get_all_tags().unwrap();
        let tag = tags.iter().find(|t| t.id == tag_id);
        assert!(tag.is_some(), "CRITICAL P0: Tag was deleted! Rename lost!");
        assert_eq!(tag.unwrap().name.as_str(), "renamed_locally");

        // Verify conflict record exists
        let conflicts = db.get_tag_delete_conflicts(false).unwrap();
        assert!(!conflicts.is_empty(),
            "CRITICAL P0: No delete conflict record!");
    }

    #[test]
    fn test_tag_delete_applies_when_no_local_changes() {
        // When local hasn't changed, remote delete should apply
        let (db, _temp) = create_test_db();

        let tag_id = db.create_tag("to_delete", None).unwrap();

        // Remote deletes with timestamp AFTER last_sync
        let remote_change = make_sync_change(
            "tag",
            &tag_id,
            "delete",
            serde_json::json!({
                "id": tag_id,
                "deleted_at": "2099-01-01 12:00:00",
            }),
            "00000000000070008000000000000099",
        );

        // Use far-future last_sync so local appears unchanged
        let result = apply_tag_change(&db, &remote_change, Some("2099-01-01 00:00:00")).unwrap();

        // Should apply
        assert_eq!(result, ApplyResult::Applied);

        // Tag should be gone
        let tags = db.get_all_tags().unwrap();
        let tag = tags.iter().find(|t| t.id == tag_id);
        assert!(tag.is_none(), "Tag should have been deleted");
    }

    // =========================================================================
    // P1: IDENTICAL CONTENT OPTIMIZATION TESTS
    // =========================================================================

    #[test]
    fn test_both_edit_to_same_content_no_conflict() {
        // P1: When both devices edit to identical content, no conflict needed
        let (db, _temp) = create_test_db();

        let note_id = db.create_note("Original").unwrap();

        // Local edits
        db.update_note(&note_id, "Same final content").unwrap();

        // Remote also edits to SAME content
        let remote_change = make_sync_change(
            "note",
            &note_id,
            "update",
            serde_json::json!({
                "id": note_id,
                "created_at": "2025-01-01 00:00:00",
                "content": "Same final content",  // Identical!
                "modified_at": "2025-01-01 12:00:00",
                "deleted_at": null,
            }),
            "00000000000070008000000000000099",
        );

        let result = apply_note_change(&db, &remote_change, None).unwrap();

        // Should apply (not conflict) since content is identical
        assert_eq!(result, ApplyResult::Applied,
            "P1: Identical content should not create conflict!");

        // Verify no conflict was created
        let conflicts = db.get_note_content_conflicts(false).unwrap();
        assert!(conflicts.is_empty(),
            "P1: Unnecessary conflict created for identical content!");
    }

    #[test]
    fn test_different_content_still_creates_conflict() {
        // Ensure different content still creates conflict (regression test)
        let (db, _temp) = create_test_db();

        let note_id = db.create_note("Original").unwrap();

        // Local edits
        db.update_note(&note_id, "Local version").unwrap();

        // Remote edits differently
        let remote_change = make_sync_change(
            "note",
            &note_id,
            "update",
            serde_json::json!({
                "id": note_id,
                "created_at": "2025-01-01 00:00:00",
                "content": "Remote version",  // Different!
                "modified_at": "2025-01-01 12:00:00",
                "deleted_at": null,
            }),
            "00000000000070008000000000000099",
        );

        let result = apply_note_change(&db, &remote_change, None).unwrap();

        // MUST be a conflict
        assert_eq!(result, ApplyResult::Conflict,
            "Different content must still create conflict!");
    }

    // =========================================================================
    // PARTIAL BATCH FAILURE TESTS
    // =========================================================================

    #[test]
    fn test_partial_batch_failure_continues_processing() {
        // CRITICAL: If change 5 of 10 fails, changes 1-4 should already be applied
        // and changes 6-10 should still be attempted and applied if valid.
        // We do NOT wrap everything in a transaction that rolls back on failure.
        let (db, _temp) = create_test_db();
        let db = std::sync::Arc::new(std::sync::Mutex::new(db));

        // Create 3 valid notes that will be created by changes 1, 3, 5
        let note1_id = uuid::Uuid::now_v7().simple().to_string();
        let note2_id = uuid::Uuid::now_v7().simple().to_string();
        let note3_id = uuid::Uuid::now_v7().simple().to_string();

        let changes = vec![
            // Change 1: Valid note create
            make_sync_change(
                "note",
                &note1_id,
                "create",
                serde_json::json!({
                    "id": note1_id,
                    "created_at": "2025-01-01 00:00:00",
                    "content": "Note 1 - should be created",
                    "modified_at": null,
                    "deleted_at": null,
                }),
                "00000000000070008000000000000099",
            ),
            // Change 2: Invalid entity type - will error
            make_sync_change(
                "invalid_type",
                "some_id",
                "create",
                serde_json::json!({}),
                "00000000000070008000000000000099",
            ),
            // Change 3: Valid note create - should still be processed after error
            make_sync_change(
                "note",
                &note2_id,
                "create",
                serde_json::json!({
                    "id": note2_id,
                    "created_at": "2025-01-01 00:00:00",
                    "content": "Note 2 - should be created despite earlier error",
                    "modified_at": null,
                    "deleted_at": null,
                }),
                "00000000000070008000000000000099",
            ),
            // Change 4: Another invalid type - will error
            make_sync_change(
                "bogus",
                "another_id",
                "update",
                serde_json::json!({}),
                "00000000000070008000000000000099",
            ),
            // Change 5: Valid note create - should still be processed
            make_sync_change(
                "note",
                &note3_id,
                "create",
                serde_json::json!({
                    "id": note3_id,
                    "created_at": "2025-01-01 00:00:00",
                    "content": "Note 3 - should be created despite multiple errors",
                    "modified_at": null,
                    "deleted_at": null,
                }),
                "00000000000070008000000000000099",
            ),
        ];

        let (applied, conflicts, errors) = apply_sync_changes(
            &db,
            &changes,
            "00000000000070008000000000000099",
            Some("Test Device"),
        ).unwrap();

        // Should have 3 successful applications
        assert_eq!(applied, 3, "All 3 valid notes should be applied!");

        // Should have 2 errors (the invalid entity types)
        assert_eq!(errors.len(), 2, "Should have 2 errors for invalid types");

        // Verify all 3 notes actually exist in the database
        let db_lock = db.lock().unwrap();

        let note1 = db_lock.get_note(&note1_id).unwrap();
        assert!(note1.is_some(), "Note 1 should exist - change before errors");

        let note2 = db_lock.get_note(&note2_id).unwrap();
        assert!(note2.is_some(), "Note 2 should exist - change after first error");

        let note3 = db_lock.get_note(&note3_id).unwrap();
        assert!(note3.is_some(), "Note 3 should exist - change after second error");
    }

    #[test]
    fn test_batch_with_all_failures_reports_all_errors() {
        // All changes fail - each should be reported individually
        let (db, _temp) = create_test_db();
        let db = std::sync::Arc::new(std::sync::Mutex::new(db));

        let changes = vec![
            make_sync_change("invalid1", "id1", "create", serde_json::json!({}), "00000000000070008000000000000099"),
            make_sync_change("invalid2", "id2", "create", serde_json::json!({}), "00000000000070008000000000000099"),
            make_sync_change("invalid3", "id3", "create", serde_json::json!({}), "00000000000070008000000000000099"),
        ];

        let (applied, conflicts, errors) = apply_sync_changes(
            &db,
            &changes,
            "00000000000070008000000000000099",
            Some("Test"),
        ).unwrap();

        assert_eq!(applied, 0);
        assert_eq!(conflicts, 0);
        assert_eq!(errors.len(), 3, "Each failure should be reported");
    }
}
