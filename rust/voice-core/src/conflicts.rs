//! Conflict resolution for Voice sync.
//!
//! This module handles:
//! - Listing unresolved conflicts
//! - Resolving conflicts (choose local, remote, or merge)
//! - Diff3-style merging for text content

use std::sync::{Arc, Mutex};

use pyo3::prelude::*;
use pyo3::types::PyDict;
use rusqlite::params;
use uuid::Uuid;

use crate::database::Database;
use crate::error::{VoiceError, VoiceResult};
use crate::merge::auto_merge_if_possible;
use crate::validation::uuid_bytes_to_hex;

/// Types of sync conflicts
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConflictType {
    NoteContent,
    NoteDelete,
    TagRename,
}

/// How to resolve a conflict
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResolutionChoice {
    KeepLocal,
    KeepRemote,
    Merge,
    KeepBoth,
}

impl ResolutionChoice {
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "keep_local" | "local" => Some(ResolutionChoice::KeepLocal),
            "keep_remote" | "remote" => Some(ResolutionChoice::KeepRemote),
            "merge" => Some(ResolutionChoice::Merge),
            "keep_both" | "both" => Some(ResolutionChoice::KeepBoth),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            ResolutionChoice::KeepLocal => "keep_local",
            ResolutionChoice::KeepRemote => "keep_remote",
            ResolutionChoice::Merge => "merge",
            ResolutionChoice::KeepBoth => "keep_both",
        }
    }
}

/// A conflict where two devices edited the same note
#[derive(Debug, Clone)]
pub struct NoteContentConflict {
    pub id: String,
    pub note_id: String,
    pub local_content: String,
    pub local_modified_at: String,
    pub local_device_id: String,
    pub local_device_name: Option<String>,
    pub remote_content: String,
    pub remote_modified_at: String,
    pub remote_device_id: String,
    pub remote_device_name: Option<String>,
    pub created_at: String,
    pub resolved_at: Option<String>,
}

/// A conflict where one device edited while another deleted
#[derive(Debug, Clone)]
pub struct NoteDeleteConflict {
    pub id: String,
    pub note_id: String,
    pub surviving_content: String,
    pub surviving_modified_at: String,
    pub surviving_device_id: String,
    pub surviving_device_name: Option<String>,
    pub deleted_at: String,
    pub deleting_device_id: String,
    pub deleting_device_name: Option<String>,
    pub created_at: String,
    pub resolved_at: Option<String>,
}

/// A conflict where two devices renamed the same tag
#[derive(Debug, Clone)]
pub struct TagRenameConflict {
    pub id: String,
    pub tag_id: String,
    pub local_name: String,
    pub local_modified_at: String,
    pub local_device_id: String,
    pub local_device_name: Option<String>,
    pub remote_name: String,
    pub remote_modified_at: String,
    pub remote_device_id: String,
    pub remote_device_name: Option<String>,
    pub created_at: String,
    pub resolved_at: Option<String>,
}

/// Conflict manager
pub struct ConflictManager<'a> {
    db: &'a Database,
}

impl<'a> ConflictManager<'a> {
    pub fn new(db: &'a Database) -> Self {
        Self { db }
    }

    /// Get count of unresolved conflicts by type
    pub fn get_unresolved_count(&self) -> VoiceResult<std::collections::HashMap<String, i64>> {
        let conn = self.db.connection();
        let mut counts = std::collections::HashMap::new();

        let note_content: i64 = conn.query_row(
            "SELECT COUNT(*) FROM conflicts_note_content WHERE resolved_at IS NULL",
            [],
            |row| row.get(0),
        )?;

        let note_delete: i64 = conn.query_row(
            "SELECT COUNT(*) FROM conflicts_note_delete WHERE resolved_at IS NULL",
            [],
            |row| row.get(0),
        )?;

        let tag_rename: i64 = conn.query_row(
            "SELECT COUNT(*) FROM conflicts_tag_rename WHERE resolved_at IS NULL",
            [],
            |row| row.get(0),
        )?;

        counts.insert("note_content".to_string(), note_content);
        counts.insert("note_delete".to_string(), note_delete);
        counts.insert("tag_rename".to_string(), tag_rename);
        counts.insert("total".to_string(), note_content + note_delete + tag_rename);

        Ok(counts)
    }

    /// Get note content conflicts
    pub fn get_note_content_conflicts(
        &self,
        include_resolved: bool,
    ) -> VoiceResult<Vec<NoteContentConflict>> {
        let conn = self.db.connection();
        let query = if include_resolved {
            "SELECT id, note_id, local_content, local_modified_at, local_device_id, \
             local_device_name, remote_content, remote_modified_at, remote_device_id, \
             remote_device_name, created_at, resolved_at FROM conflicts_note_content \
             ORDER BY created_at DESC"
        } else {
            "SELECT id, note_id, local_content, local_modified_at, local_device_id, \
             local_device_name, remote_content, remote_modified_at, remote_device_id, \
             remote_device_name, created_at, resolved_at FROM conflicts_note_content \
             WHERE resolved_at IS NULL ORDER BY created_at DESC"
        };

        let mut stmt = conn.prepare(query)?;
        let rows = stmt.query_map([], |row| {
            let id_bytes: Vec<u8> = row.get(0)?;
            let note_id_bytes: Vec<u8> = row.get(1)?;
            let local_device_id_bytes: Option<Vec<u8>> = row.get(4)?;
            let remote_device_id_bytes: Option<Vec<u8>> = row.get(8)?;

            Ok(NoteContentConflict {
                id: uuid_bytes_to_hex(&id_bytes).unwrap_or_default(),
                note_id: uuid_bytes_to_hex(&note_id_bytes).unwrap_or_default(),
                local_content: row.get(2)?,
                local_modified_at: row.get(3)?,
                local_device_id: local_device_id_bytes
                    .and_then(|b| uuid_bytes_to_hex(&b).ok())
                    .unwrap_or_default(),
                local_device_name: row.get(5)?,
                remote_content: row.get(6)?,
                remote_modified_at: row.get(7)?,
                remote_device_id: remote_device_id_bytes
                    .and_then(|b| uuid_bytes_to_hex(&b).ok())
                    .unwrap_or_default(),
                remote_device_name: row.get(9)?,
                created_at: row.get(10)?,
                resolved_at: row.get(11)?,
            })
        })?;

        let mut conflicts = Vec::new();
        for row in rows {
            conflicts.push(row?);
        }
        Ok(conflicts)
    }

    /// Get note delete conflicts
    pub fn get_note_delete_conflicts(
        &self,
        include_resolved: bool,
    ) -> VoiceResult<Vec<NoteDeleteConflict>> {
        let conn = self.db.connection();
        let query = if include_resolved {
            "SELECT id, note_id, surviving_content, surviving_modified_at, surviving_device_id, \
             surviving_device_name, deleted_at, deleting_device_id, deleting_device_name, \
             created_at, resolved_at FROM conflicts_note_delete ORDER BY created_at DESC"
        } else {
            "SELECT id, note_id, surviving_content, surviving_modified_at, surviving_device_id, \
             surviving_device_name, deleted_at, deleting_device_id, deleting_device_name, \
             created_at, resolved_at FROM conflicts_note_delete WHERE resolved_at IS NULL \
             ORDER BY created_at DESC"
        };

        let mut stmt = conn.prepare(query)?;
        let rows = stmt.query_map([], |row| {
            let id_bytes: Vec<u8> = row.get(0)?;
            let note_id_bytes: Vec<u8> = row.get(1)?;
            let surviving_device_id_bytes: Option<Vec<u8>> = row.get(4)?;
            let deleting_device_id_bytes: Option<Vec<u8>> = row.get(7)?;

            Ok(NoteDeleteConflict {
                id: uuid_bytes_to_hex(&id_bytes).unwrap_or_default(),
                note_id: uuid_bytes_to_hex(&note_id_bytes).unwrap_or_default(),
                surviving_content: row.get(2)?,
                surviving_modified_at: row.get(3)?,
                surviving_device_id: surviving_device_id_bytes
                    .and_then(|b| uuid_bytes_to_hex(&b).ok())
                    .unwrap_or_default(),
                surviving_device_name: row.get(5)?,
                deleted_at: row.get(6)?,
                deleting_device_id: deleting_device_id_bytes
                    .and_then(|b| uuid_bytes_to_hex(&b).ok())
                    .unwrap_or_default(),
                deleting_device_name: row.get(8)?,
                created_at: row.get(9)?,
                resolved_at: row.get(10)?,
            })
        })?;

        let mut conflicts = Vec::new();
        for row in rows {
            conflicts.push(row?);
        }
        Ok(conflicts)
    }

    /// Get tag rename conflicts
    pub fn get_tag_rename_conflicts(
        &self,
        include_resolved: bool,
    ) -> VoiceResult<Vec<TagRenameConflict>> {
        let conn = self.db.connection();
        let query = if include_resolved {
            "SELECT id, tag_id, local_name, local_modified_at, local_device_id, \
             local_device_name, remote_name, remote_modified_at, remote_device_id, \
             remote_device_name, created_at, resolved_at FROM conflicts_tag_rename \
             ORDER BY created_at DESC"
        } else {
            "SELECT id, tag_id, local_name, local_modified_at, local_device_id, \
             local_device_name, remote_name, remote_modified_at, remote_device_id, \
             remote_device_name, created_at, resolved_at FROM conflicts_tag_rename \
             WHERE resolved_at IS NULL ORDER BY created_at DESC"
        };

        let mut stmt = conn.prepare(query)?;
        let rows = stmt.query_map([], |row| {
            let id_bytes: Vec<u8> = row.get(0)?;
            let tag_id_bytes: Vec<u8> = row.get(1)?;
            let local_device_id_bytes: Option<Vec<u8>> = row.get(4)?;
            let remote_device_id_bytes: Option<Vec<u8>> = row.get(8)?;

            Ok(TagRenameConflict {
                id: uuid_bytes_to_hex(&id_bytes).unwrap_or_default(),
                tag_id: uuid_bytes_to_hex(&tag_id_bytes).unwrap_or_default(),
                local_name: row.get(2)?,
                local_modified_at: row.get(3)?,
                local_device_id: local_device_id_bytes
                    .and_then(|b| uuid_bytes_to_hex(&b).ok())
                    .unwrap_or_default(),
                local_device_name: row.get(5)?,
                remote_name: row.get(6)?,
                remote_modified_at: row.get(7)?,
                remote_device_id: remote_device_id_bytes
                    .and_then(|b| uuid_bytes_to_hex(&b).ok())
                    .unwrap_or_default(),
                remote_device_name: row.get(9)?,
                created_at: row.get(10)?,
                resolved_at: row.get(11)?,
            })
        })?;

        let mut conflicts = Vec::new();
        for row in rows {
            conflicts.push(row?);
        }
        Ok(conflicts)
    }

    /// Resolve a note content conflict
    pub fn resolve_note_content_conflict(
        &self,
        conflict_id: &str,
        choice: ResolutionChoice,
        merged_content: Option<&str>,
    ) -> VoiceResult<bool> {
        let conflict_uuid = Uuid::parse_str(conflict_id)?;
        let conflict_id_bytes = conflict_uuid.as_bytes().to_vec();

        let conn = self.db.connection();

        // Get the conflict
        let (note_id_bytes, local_content, remote_content): (Vec<u8>, String, String) = conn
            .query_row(
                "SELECT note_id, local_content, remote_content FROM conflicts_note_content WHERE id = ?",
                [&conflict_id_bytes],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .map_err(|_| VoiceError::NotFound("Conflict not found".to_string()))?;

        // Determine new content
        let new_content = match choice {
            ResolutionChoice::KeepLocal => local_content,
            ResolutionChoice::KeepRemote => remote_content,
            ResolutionChoice::Merge => {
                merged_content
                    .ok_or_else(|| {
                        VoiceError::validation("merged_content", "required for MERGE resolution")
                    })?
                    .to_string()
            }
            ResolutionChoice::KeepBoth => {
                return Err(VoiceError::validation(
                    "choice",
                    "keep_both not valid for note content conflicts",
                ));
            }
        };

        // Update the note
        conn.execute(
            "UPDATE notes SET content = ?, modified_at = datetime('now') WHERE id = ?",
            params![new_content, note_id_bytes],
        )?;

        // Mark conflict as resolved
        conn.execute(
            "UPDATE conflicts_note_content SET resolved_at = datetime('now') WHERE id = ?",
            [conflict_id_bytes],
        )?;

        Ok(true)
    }

    /// Resolve a note delete conflict
    pub fn resolve_note_delete_conflict(
        &self,
        conflict_id: &str,
        choice: ResolutionChoice,
    ) -> VoiceResult<bool> {
        let conflict_uuid = Uuid::parse_str(conflict_id)?;
        let conflict_id_bytes = conflict_uuid.as_bytes().to_vec();

        let conn = self.db.connection();

        // Get the conflict
        let (note_id_bytes, surviving_content): (Vec<u8>, String) = conn
            .query_row(
                "SELECT note_id, surviving_content FROM conflicts_note_delete WHERE id = ?",
                [&conflict_id_bytes],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .map_err(|_| VoiceError::NotFound("Conflict not found".to_string()))?;

        match choice {
            ResolutionChoice::KeepBoth => {
                // Restore the note with surviving content
                conn.execute(
                    "UPDATE notes SET content = ?, deleted_at = NULL, modified_at = datetime('now') WHERE id = ?",
                    params![surviving_content, note_id_bytes],
                )?;
            }
            ResolutionChoice::KeepRemote => {
                // Accept the deletion - note stays deleted
            }
            _ => {
                return Err(VoiceError::validation(
                    "choice",
                    "note delete conflicts can only be resolved with keep_both or keep_remote",
                ));
            }
        }

        // Mark conflict as resolved
        conn.execute(
            "UPDATE conflicts_note_delete SET resolved_at = datetime('now') WHERE id = ?",
            [conflict_id_bytes],
        )?;

        Ok(true)
    }

    /// Resolve a tag rename conflict
    pub fn resolve_tag_rename_conflict(
        &self,
        conflict_id: &str,
        choice: ResolutionChoice,
    ) -> VoiceResult<bool> {
        let conflict_uuid = Uuid::parse_str(conflict_id)?;
        let conflict_id_bytes = conflict_uuid.as_bytes().to_vec();

        let conn = self.db.connection();

        // Get the conflict
        let (tag_id_bytes, local_name, remote_name): (Vec<u8>, String, String) = conn
            .query_row(
                "SELECT tag_id, local_name, remote_name FROM conflicts_tag_rename WHERE id = ?",
                [&conflict_id_bytes],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .map_err(|_| VoiceError::NotFound("Conflict not found".to_string()))?;

        let new_name = match choice {
            ResolutionChoice::KeepLocal => local_name,
            ResolutionChoice::KeepRemote => remote_name,
            _ => {
                return Err(VoiceError::validation(
                    "choice",
                    "tag rename conflicts can only be resolved with keep_local or keep_remote",
                ));
            }
        };

        // Update the tag
        conn.execute(
            "UPDATE tags SET name = ?, modified_at = datetime('now') WHERE id = ?",
            params![new_name, tag_id_bytes],
        )?;

        // Mark conflict as resolved
        conn.execute(
            "UPDATE conflicts_tag_rename SET resolved_at = datetime('now') WHERE id = ?",
            [conflict_id_bytes],
        )?;

        Ok(true)
    }

    /// Find and resolve a conflict by ID prefix
    pub fn find_and_resolve_conflict(
        &self,
        conflict_id_prefix: &str,
        choice: ResolutionChoice,
        merged_content: Option<&str>,
    ) -> VoiceResult<(bool, String, Option<String>)> {
        // Check note content conflicts
        for c in self.get_note_content_conflicts(false)? {
            if c.id.starts_with(conflict_id_prefix) || c.id == conflict_id_prefix {
                if !matches!(
                    choice,
                    ResolutionChoice::KeepLocal | ResolutionChoice::KeepRemote | ResolutionChoice::Merge
                ) {
                    return Ok((
                        false,
                        "note_content".to_string(),
                        Some("Note content conflicts can only be resolved with keep_local, keep_remote, or merge".to_string()),
                    ));
                }

                let actual_merged = if choice == ResolutionChoice::Merge && merged_content.is_none() {
                    // Try auto-merge
                    auto_merge_if_possible(&c.local_content, &c.remote_content, None)
                } else {
                    merged_content.map(String::from)
                };

                if choice == ResolutionChoice::Merge && actual_merged.is_none() {
                    return Ok((
                        false,
                        "note_content".to_string(),
                        Some("Cannot auto-merge conflicting content. Provide merged_content explicitly.".to_string()),
                    ));
                }

                let result = self.resolve_note_content_conflict(&c.id, choice, actual_merged.as_deref())?;
                return Ok((result, "note_content".to_string(), None));
            }
        }

        // Check note delete conflicts
        for c in self.get_note_delete_conflicts(false)? {
            if c.id.starts_with(conflict_id_prefix) || c.id == conflict_id_prefix {
                if !matches!(choice, ResolutionChoice::KeepBoth | ResolutionChoice::KeepRemote) {
                    return Ok((
                        false,
                        "note_delete".to_string(),
                        Some("Note delete conflicts can only be resolved with keep_both or keep_remote".to_string()),
                    ));
                }

                let result = self.resolve_note_delete_conflict(&c.id, choice)?;
                return Ok((result, "note_delete".to_string(), None));
            }
        }

        // Check tag rename conflicts
        for c in self.get_tag_rename_conflicts(false)? {
            if c.id.starts_with(conflict_id_prefix) || c.id == conflict_id_prefix {
                if !matches!(choice, ResolutionChoice::KeepLocal | ResolutionChoice::KeepRemote) {
                    return Ok((
                        false,
                        "tag_rename".to_string(),
                        Some("Tag rename conflicts can only be resolved with keep_local or keep_remote".to_string()),
                    ));
                }

                let result = self.resolve_tag_rename_conflict(&c.id, choice)?;
                return Ok((result, "tag_rename".to_string(), None));
            }
        }

        Ok((
            false,
            String::new(),
            Some(format!("Conflict with ID starting with '{}' not found", conflict_id_prefix)),
        ))
    }
}

// ============================================================================
// Python bindings
// ============================================================================

/// Python wrapper for NoteContentConflict
#[pyclass(name = "NoteContentConflict")]
#[derive(Clone)]
pub struct PyNoteContentConflict {
    inner: NoteContentConflict,
}

#[pymethods]
impl PyNoteContentConflict {
    #[getter]
    fn id(&self) -> &str {
        &self.inner.id
    }

    #[getter]
    fn note_id(&self) -> &str {
        &self.inner.note_id
    }

    #[getter]
    fn local_content(&self) -> &str {
        &self.inner.local_content
    }

    #[getter]
    fn local_modified_at(&self) -> &str {
        &self.inner.local_modified_at
    }

    #[getter]
    fn local_device_id(&self) -> &str {
        &self.inner.local_device_id
    }

    #[getter]
    fn local_device_name(&self) -> Option<&str> {
        self.inner.local_device_name.as_deref()
    }

    #[getter]
    fn remote_content(&self) -> &str {
        &self.inner.remote_content
    }

    #[getter]
    fn remote_modified_at(&self) -> &str {
        &self.inner.remote_modified_at
    }

    #[getter]
    fn remote_device_id(&self) -> &str {
        &self.inner.remote_device_id
    }

    #[getter]
    fn remote_device_name(&self) -> Option<&str> {
        self.inner.remote_device_name.as_deref()
    }

    #[getter]
    fn created_at(&self) -> &str {
        &self.inner.created_at
    }

    #[getter]
    fn resolved_at(&self) -> Option<&str> {
        self.inner.resolved_at.as_deref()
    }
}

/// Python wrapper for NoteDeleteConflict
#[pyclass(name = "NoteDeleteConflict")]
#[derive(Clone)]
pub struct PyNoteDeleteConflict {
    inner: NoteDeleteConflict,
}

#[pymethods]
impl PyNoteDeleteConflict {
    #[getter]
    fn id(&self) -> &str {
        &self.inner.id
    }

    #[getter]
    fn note_id(&self) -> &str {
        &self.inner.note_id
    }

    #[getter]
    fn surviving_content(&self) -> &str {
        &self.inner.surviving_content
    }

    #[getter]
    fn surviving_modified_at(&self) -> &str {
        &self.inner.surviving_modified_at
    }

    #[getter]
    fn surviving_device_id(&self) -> &str {
        &self.inner.surviving_device_id
    }

    #[getter]
    fn surviving_device_name(&self) -> Option<&str> {
        self.inner.surviving_device_name.as_deref()
    }

    #[getter]
    fn deleted_at(&self) -> &str {
        &self.inner.deleted_at
    }

    #[getter]
    fn deleting_device_id(&self) -> &str {
        &self.inner.deleting_device_id
    }

    #[getter]
    fn deleting_device_name(&self) -> Option<&str> {
        self.inner.deleting_device_name.as_deref()
    }

    #[getter]
    fn created_at(&self) -> &str {
        &self.inner.created_at
    }

    #[getter]
    fn resolved_at(&self) -> Option<&str> {
        self.inner.resolved_at.as_deref()
    }
}

/// Python wrapper for TagRenameConflict
#[pyclass(name = "TagRenameConflict")]
#[derive(Clone)]
pub struct PyTagRenameConflict {
    inner: TagRenameConflict,
}

#[pymethods]
impl PyTagRenameConflict {
    #[getter]
    fn id(&self) -> &str {
        &self.inner.id
    }

    #[getter]
    fn tag_id(&self) -> &str {
        &self.inner.tag_id
    }

    #[getter]
    fn local_name(&self) -> &str {
        &self.inner.local_name
    }

    #[getter]
    fn local_modified_at(&self) -> &str {
        &self.inner.local_modified_at
    }

    #[getter]
    fn local_device_id(&self) -> &str {
        &self.inner.local_device_id
    }

    #[getter]
    fn local_device_name(&self) -> Option<&str> {
        self.inner.local_device_name.as_deref()
    }

    #[getter]
    fn remote_name(&self) -> &str {
        &self.inner.remote_name
    }

    #[getter]
    fn remote_modified_at(&self) -> &str {
        &self.inner.remote_modified_at
    }

    #[getter]
    fn remote_device_id(&self) -> &str {
        &self.inner.remote_device_id
    }

    #[getter]
    fn remote_device_name(&self) -> Option<&str> {
        self.inner.remote_device_name.as_deref()
    }

    #[getter]
    fn created_at(&self) -> &str {
        &self.inner.created_at
    }

    #[getter]
    fn resolved_at(&self) -> Option<&str> {
        self.inner.resolved_at.as_deref()
    }
}

/// Python wrapper for ConflictManager
#[pyclass(name = "ConflictManager")]
pub struct PyConflictManager {
    db: Arc<Mutex<Database>>,
}

#[pymethods]
impl PyConflictManager {
    #[new]
    fn new(db: &crate::database::PyDatabase) -> PyResult<Self> {
        // This needs to share the database reference
        // For now, we'll create a simplified version
        Err(pyo3::exceptions::PyNotImplementedError::new_err(
            "ConflictManager must be created from PyDatabase - use db.get_conflict_manager()",
        ))
    }

    /// Get unresolved conflict counts
    fn get_unresolved_count(&self, py: Python<'_>) -> PyResult<PyObject> {
        let db = self.db.lock().unwrap();
        let manager = ConflictManager::new(&db);
        let counts = manager.get_unresolved_count()?;

        let dict = PyDict::new(py);
        for (key, value) in counts {
            dict.set_item(key, value)?;
        }
        Ok(dict.into())
    }

    /// Get note content conflicts
    #[pyo3(signature = (include_resolved=false))]
    fn get_note_content_conflicts(&self, include_resolved: bool) -> PyResult<Vec<PyNoteContentConflict>> {
        let db = self.db.lock().unwrap();
        let manager = ConflictManager::new(&db);
        let conflicts = manager.get_note_content_conflicts(include_resolved)?;
        Ok(conflicts.into_iter().map(|c| PyNoteContentConflict { inner: c }).collect())
    }

    /// Get note delete conflicts
    #[pyo3(signature = (include_resolved=false))]
    fn get_note_delete_conflicts(&self, include_resolved: bool) -> PyResult<Vec<PyNoteDeleteConflict>> {
        let db = self.db.lock().unwrap();
        let manager = ConflictManager::new(&db);
        let conflicts = manager.get_note_delete_conflicts(include_resolved)?;
        Ok(conflicts.into_iter().map(|c| PyNoteDeleteConflict { inner: c }).collect())
    }

    /// Get tag rename conflicts
    #[pyo3(signature = (include_resolved=false))]
    fn get_tag_rename_conflicts(&self, include_resolved: bool) -> PyResult<Vec<PyTagRenameConflict>> {
        let db = self.db.lock().unwrap();
        let manager = ConflictManager::new(&db);
        let conflicts = manager.get_tag_rename_conflicts(include_resolved)?;
        Ok(conflicts.into_iter().map(|c| PyTagRenameConflict { inner: c }).collect())
    }

    /// Resolve a note content conflict
    #[pyo3(signature = (conflict_id, choice, merged_content=None))]
    fn resolve_note_content_conflict(
        &self,
        conflict_id: &str,
        choice: &str,
        merged_content: Option<&str>,
    ) -> PyResult<bool> {
        let resolution = ResolutionChoice::from_str(choice)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Invalid resolution choice"))?;

        let db = self.db.lock().unwrap();
        let manager = ConflictManager::new(&db);
        let result = manager.resolve_note_content_conflict(conflict_id, resolution, merged_content)?;
        Ok(result)
    }

    /// Resolve a note delete conflict
    fn resolve_note_delete_conflict(&self, conflict_id: &str, choice: &str) -> PyResult<bool> {
        let resolution = ResolutionChoice::from_str(choice)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Invalid resolution choice"))?;

        let db = self.db.lock().unwrap();
        let manager = ConflictManager::new(&db);
        let result = manager.resolve_note_delete_conflict(conflict_id, resolution)?;
        Ok(result)
    }

    /// Resolve a tag rename conflict
    fn resolve_tag_rename_conflict(&self, conflict_id: &str, choice: &str) -> PyResult<bool> {
        let resolution = ResolutionChoice::from_str(choice)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Invalid resolution choice"))?;

        let db = self.db.lock().unwrap();
        let manager = ConflictManager::new(&db);
        let result = manager.resolve_tag_rename_conflict(conflict_id, resolution)?;
        Ok(result)
    }

    /// Find and resolve a conflict by ID prefix
    #[pyo3(signature = (conflict_id_prefix, choice, merged_content=None))]
    fn find_and_resolve_conflict(
        &self,
        py: Python<'_>,
        conflict_id_prefix: &str,
        choice: &str,
        merged_content: Option<&str>,
    ) -> PyResult<PyObject> {
        let resolution = ResolutionChoice::from_str(choice)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Invalid resolution choice"))?;

        let db = self.db.lock().unwrap();
        let manager = ConflictManager::new(&db);
        let (success, conflict_type, error) =
            manager.find_and_resolve_conflict(conflict_id_prefix, resolution, merged_content)?;

        let dict = PyDict::new(py);
        dict.set_item("success", success)?;
        dict.set_item("conflict_type", conflict_type)?;
        dict.set_item("error", error)?;
        Ok(dict.into())
    }
}
