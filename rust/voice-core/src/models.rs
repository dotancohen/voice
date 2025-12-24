//! Data models for Voice.
//!
//! This module defines the core entities: Note, Tag, and NoteTag.
//! All IDs are UUID7 stored as 16 bytes internally, converted to hex strings for JSON/Python.

use chrono::{DateTime, Utc};
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Represents a note in the system.
///
/// Notes contain text content and metadata about creation, modification,
/// and deletion times. All timestamps are accurate to the second.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Note {
    /// Unique identifier for the note (UUID7 as bytes)
    pub id: Uuid,
    /// When the note was created (never NULL)
    pub created_at: DateTime<Utc>,
    /// The note text content
    pub content: String,
    /// UUID7 of the device that last modified this note
    pub device_id: Uuid,
    /// When the note was last modified (None if never modified)
    pub modified_at: Option<DateTime<Utc>>,
    /// When the note was deleted (None if not deleted, soft delete)
    pub deleted_at: Option<DateTime<Utc>>,
}

impl Note {
    /// Create a new note with the given content
    pub fn new(content: String, device_id: Uuid) -> Self {
        Self {
            id: Uuid::now_v7(),
            created_at: Utc::now(),
            content,
            device_id,
            modified_at: None,
            deleted_at: None,
        }
    }

    /// Get the note ID as a hex string
    pub fn id_hex(&self) -> String {
        self.id.simple().to_string()
    }

    /// Get the device ID as a hex string
    pub fn device_id_hex(&self) -> String {
        self.device_id.simple().to_string()
    }

    /// Check if the note is deleted
    pub fn is_deleted(&self) -> bool {
        self.deleted_at.is_some()
    }
}

/// Represents a tag in the hierarchical tag system.
///
/// Tags can have parent-child relationships, forming a tree structure.
/// A tag with parent_id=None is a root-level tag.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Tag {
    /// Unique identifier for the tag (UUID7 as bytes)
    pub id: Uuid,
    /// Display name of the tag (must be unique within parent)
    pub name: String,
    /// UUID7 of the device that last modified this tag
    pub device_id: Uuid,
    /// ID of the parent tag (None for root tags)
    pub parent_id: Option<Uuid>,
    /// When the tag was created
    pub created_at: Option<DateTime<Utc>>,
    /// When the tag was last modified (None if never modified)
    pub modified_at: Option<DateTime<Utc>>,
}

impl Tag {
    /// Create a new tag with the given name
    pub fn new(name: String, device_id: Uuid, parent_id: Option<Uuid>) -> Self {
        Self {
            id: Uuid::now_v7(),
            name,
            device_id,
            parent_id,
            created_at: Some(Utc::now()),
            modified_at: None,
        }
    }

    /// Get the tag ID as a hex string
    pub fn id_hex(&self) -> String {
        self.id.simple().to_string()
    }

    /// Get the device ID as a hex string
    pub fn device_id_hex(&self) -> String {
        self.device_id.simple().to_string()
    }

    /// Get the parent ID as a hex string (if present)
    pub fn parent_id_hex(&self) -> Option<String> {
        self.parent_id.map(|id| id.simple().to_string())
    }
}

/// Represents the association between a note and a tag.
///
/// This is used for syncing note-tag relationships.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NoteTag {
    /// UUID7 of the note
    pub note_id: Uuid,
    /// UUID7 of the tag
    pub tag_id: Uuid,
    /// When the association was created
    pub created_at: DateTime<Utc>,
    /// UUID7 of the device that created this association
    pub device_id: Uuid,
    /// When the association was modified (for sync tracking)
    pub modified_at: Option<DateTime<Utc>>,
    /// When the association was removed (None if active)
    pub deleted_at: Option<DateTime<Utc>>,
}

impl NoteTag {
    /// Create a new note-tag association
    pub fn new(note_id: Uuid, tag_id: Uuid, device_id: Uuid) -> Self {
        Self {
            note_id,
            tag_id,
            created_at: Utc::now(),
            device_id,
            modified_at: None,
            deleted_at: None,
        }
    }

    /// Get the note ID as a hex string
    pub fn note_id_hex(&self) -> String {
        self.note_id.simple().to_string()
    }

    /// Get the tag ID as a hex string
    pub fn tag_id_hex(&self) -> String {
        self.tag_id.simple().to_string()
    }

    /// Get the device ID as a hex string
    pub fn device_id_hex(&self) -> String {
        self.device_id.simple().to_string()
    }

    /// Check if the association is deleted
    pub fn is_deleted(&self) -> bool {
        self.deleted_at.is_some()
    }
}

// ============================================================================
// Python bindings
// ============================================================================

/// Python wrapper for Note
#[pyclass(name = "Note")]
#[derive(Clone)]
pub struct PyNote {
    inner: Note,
}

#[pymethods]
impl PyNote {
    #[new]
    #[pyo3(signature = (content, device_id=None))]
    fn new(content: String, device_id: Option<String>) -> PyResult<Self> {
        let device_uuid = match device_id {
            Some(id) => Uuid::parse_str(&id)
                .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?,
            None => Uuid::now_v7(),
        };
        Ok(Self {
            inner: Note::new(content, device_uuid),
        })
    }

    #[getter]
    fn id(&self) -> String {
        self.inner.id_hex()
    }

    #[getter]
    fn created_at(&self) -> String {
        self.inner.created_at.to_rfc3339()
    }

    #[getter]
    fn content(&self) -> &str {
        &self.inner.content
    }

    #[getter]
    fn device_id(&self) -> String {
        self.inner.device_id_hex()
    }

    #[getter]
    fn modified_at(&self) -> Option<String> {
        self.inner.modified_at.map(|dt| dt.to_rfc3339())
    }

    #[getter]
    fn deleted_at(&self) -> Option<String> {
        self.inner.deleted_at.map(|dt| dt.to_rfc3339())
    }

    fn is_deleted(&self) -> bool {
        self.inner.is_deleted()
    }

    fn __repr__(&self) -> String {
        format!(
            "Note(id='{}', content='{:.30}...', created_at='{}')",
            self.inner.id_hex(),
            self.inner.content,
            self.inner.created_at.to_rfc3339()
        )
    }
}

impl PyNote {
    pub fn from_note(note: Note) -> Self {
        Self { inner: note }
    }

    pub fn into_inner(self) -> Note {
        self.inner
    }

    pub fn inner(&self) -> &Note {
        &self.inner
    }
}

/// Python wrapper for Tag
#[pyclass(name = "Tag")]
#[derive(Clone)]
pub struct PyTag {
    inner: Tag,
}

#[pymethods]
impl PyTag {
    #[new]
    #[pyo3(signature = (name, device_id=None, parent_id=None))]
    fn new(name: String, device_id: Option<String>, parent_id: Option<String>) -> PyResult<Self> {
        let device_uuid = match device_id {
            Some(id) => Uuid::parse_str(&id)
                .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?,
            None => Uuid::now_v7(),
        };
        let parent_uuid = match parent_id {
            Some(id) => Some(
                Uuid::parse_str(&id)
                    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?,
            ),
            None => None,
        };
        Ok(Self {
            inner: Tag::new(name, device_uuid, parent_uuid),
        })
    }

    #[getter]
    fn id(&self) -> String {
        self.inner.id_hex()
    }

    #[getter]
    fn name(&self) -> &str {
        &self.inner.name
    }

    #[getter]
    fn device_id(&self) -> String {
        self.inner.device_id_hex()
    }

    #[getter]
    fn parent_id(&self) -> Option<String> {
        self.inner.parent_id_hex()
    }

    #[getter]
    fn created_at(&self) -> Option<String> {
        self.inner.created_at.map(|dt| dt.to_rfc3339())
    }

    #[getter]
    fn modified_at(&self) -> Option<String> {
        self.inner.modified_at.map(|dt| dt.to_rfc3339())
    }

    fn __repr__(&self) -> String {
        format!(
            "Tag(id='{}', name='{}', parent_id={:?})",
            self.inner.id_hex(),
            self.inner.name,
            self.inner.parent_id_hex()
        )
    }
}

impl PyTag {
    pub fn from_tag(tag: Tag) -> Self {
        Self { inner: tag }
    }

    pub fn into_inner(self) -> Tag {
        self.inner
    }

    pub fn inner(&self) -> &Tag {
        &self.inner
    }
}

/// Python wrapper for NoteTag
#[pyclass(name = "NoteTag")]
#[derive(Clone)]
pub struct PyNoteTag {
    inner: NoteTag,
}

#[pymethods]
impl PyNoteTag {
    #[new]
    #[pyo3(signature = (note_id, tag_id, device_id=None))]
    fn new(note_id: String, tag_id: String, device_id: Option<String>) -> PyResult<Self> {
        let note_uuid = Uuid::parse_str(&note_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let tag_uuid = Uuid::parse_str(&tag_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let device_uuid = match device_id {
            Some(id) => Uuid::parse_str(&id)
                .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?,
            None => Uuid::now_v7(),
        };
        Ok(Self {
            inner: NoteTag::new(note_uuid, tag_uuid, device_uuid),
        })
    }

    #[getter]
    fn note_id(&self) -> String {
        self.inner.note_id_hex()
    }

    #[getter]
    fn tag_id(&self) -> String {
        self.inner.tag_id_hex()
    }

    #[getter]
    fn created_at(&self) -> String {
        self.inner.created_at.to_rfc3339()
    }

    #[getter]
    fn device_id(&self) -> String {
        self.inner.device_id_hex()
    }

    #[getter]
    fn modified_at(&self) -> Option<String> {
        self.inner.modified_at.map(|dt| dt.to_rfc3339())
    }

    #[getter]
    fn deleted_at(&self) -> Option<String> {
        self.inner.deleted_at.map(|dt| dt.to_rfc3339())
    }

    fn is_deleted(&self) -> bool {
        self.inner.is_deleted()
    }

    fn __repr__(&self) -> String {
        format!(
            "NoteTag(note_id='{}', tag_id='{}', created_at='{}')",
            self.inner.note_id_hex(),
            self.inner.tag_id_hex(),
            self.inner.created_at.to_rfc3339()
        )
    }
}

impl PyNoteTag {
    pub fn from_note_tag(note_tag: NoteTag) -> Self {
        Self { inner: note_tag }
    }

    pub fn into_inner(self) -> NoteTag {
        self.inner
    }

    pub fn inner(&self) -> &NoteTag {
        &self.inner
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_note_creation() {
        let device_id = Uuid::now_v7();
        let note = Note::new("Test content".to_string(), device_id);

        assert!(!note.id.is_nil());
        assert_eq!(note.content, "Test content");
        assert_eq!(note.device_id, device_id);
        assert!(note.modified_at.is_none());
        assert!(note.deleted_at.is_none());
        assert!(!note.is_deleted());
    }

    #[test]
    fn test_tag_creation() {
        let device_id = Uuid::now_v7();
        let tag = Tag::new("Work".to_string(), device_id, None);

        assert!(!tag.id.is_nil());
        assert_eq!(tag.name, "Work");
        assert!(tag.parent_id.is_none());
    }

    #[test]
    fn test_tag_with_parent() {
        let device_id = Uuid::now_v7();
        let parent = Tag::new("Work".to_string(), device_id, None);
        let child = Tag::new("Projects".to_string(), device_id, Some(parent.id));

        assert_eq!(child.parent_id, Some(parent.id));
    }

    #[test]
    fn test_note_tag_creation() {
        let device_id = Uuid::now_v7();
        let note = Note::new("Test".to_string(), device_id);
        let tag = Tag::new("Work".to_string(), device_id, None);
        let note_tag = NoteTag::new(note.id, tag.id, device_id);

        assert_eq!(note_tag.note_id, note.id);
        assert_eq!(note_tag.tag_id, tag.id);
        assert!(!note_tag.is_deleted());
    }

    #[test]
    fn test_id_hex_format() {
        let device_id = Uuid::now_v7();
        let note = Note::new("Test".to_string(), device_id);

        let hex = note.id_hex();
        assert_eq!(hex.len(), 32); // UUID without hyphens
        assert!(hex.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
