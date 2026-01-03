//! Python bindings for VoiceCore.
//!
//! This crate provides PyO3 bindings to expose the voicecore library to Python.

use pyo3::create_exception;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use voicecore_lib::{config, database, error, merge, search, sync_client, sync_server, validation};

// ============================================================================
// Error types
// ============================================================================

create_exception!(voicecore, ValidationError, pyo3::exceptions::PyException);
create_exception!(voicecore, DatabaseError, pyo3::exceptions::PyException);
create_exception!(voicecore, SyncError, pyo3::exceptions::PyException);

fn voice_error_to_pyerr(err: error::VoiceError) -> PyErr {
    match &err {
        error::VoiceError::Validation { field, message } => {
            // Format as "field: message" for Python to parse
            ValidationError::new_err(format!("{}: {}", field, message))
        }
        error::VoiceError::Database(_) | error::VoiceError::DatabaseOperation(_) => {
            DatabaseError::new_err(err.to_string())
        }
        error::VoiceError::Sync(_) | error::VoiceError::Network(_) => {
            SyncError::new_err(err.to_string())
        }
        _ => pyo3::exceptions::PyRuntimeError::new_err(err.to_string()),
    }
}

fn validation_error_to_pyerr(err: error::ValidationError) -> PyErr {
    ValidationError::new_err(err.to_string())
}

// ============================================================================
// Helper to convert NoteRow to PyDict
// ============================================================================

fn note_row_to_dict<'py>(py: Python<'py>, note: &database::NoteRow) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("id", &note.id)?;
    dict.set_item("created_at", &note.created_at)?;
    dict.set_item("content", &note.content)?;
    dict.set_item("modified_at", &note.modified_at)?;
    dict.set_item("deleted_at", &note.deleted_at)?;
    dict.set_item("tag_names", &note.tag_names)?;
    Ok(dict)
}

fn tag_row_to_dict<'py>(py: Python<'py>, tag: &database::TagRow) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("id", &tag.id)?;
    dict.set_item("name", &tag.name)?;
    dict.set_item("parent_id", &tag.parent_id)?;
    dict.set_item("created_at", &tag.created_at)?;
    dict.set_item("modified_at", &tag.modified_at)?;
    Ok(dict)
}

fn note_attachment_row_to_dict<'py>(py: Python<'py>, attachment: &database::NoteAttachmentRow) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("id", &attachment.id)?;
    dict.set_item("note_id", &attachment.note_id)?;
    dict.set_item("attachment_id", &attachment.attachment_id)?;
    dict.set_item("attachment_type", &attachment.attachment_type)?;
    dict.set_item("created_at", &attachment.created_at)?;
    dict.set_item("device_id", &attachment.device_id)?;
    dict.set_item("modified_at", &attachment.modified_at)?;
    dict.set_item("deleted_at", &attachment.deleted_at)?;
    Ok(dict)
}

fn audio_file_row_to_dict<'py>(py: Python<'py>, audio_file: &database::AudioFileRow) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("id", &audio_file.id)?;
    dict.set_item("imported_at", &audio_file.imported_at)?;
    dict.set_item("filename", &audio_file.filename)?;
    dict.set_item("file_created_at", &audio_file.file_created_at)?;
    dict.set_item("summary", &audio_file.summary)?;
    dict.set_item("device_id", &audio_file.device_id)?;
    dict.set_item("modified_at", &audio_file.modified_at)?;
    dict.set_item("deleted_at", &audio_file.deleted_at)?;
    Ok(dict)
}

fn transcription_row_to_dict<'py>(py: Python<'py>, transcription: &database::TranscriptionRow) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("id", &transcription.id)?;
    dict.set_item("audio_file_id", &transcription.audio_file_id)?;
    dict.set_item("content", &transcription.content)?;
    dict.set_item("content_segments", &transcription.content_segments)?;
    dict.set_item("service", &transcription.service)?;
    dict.set_item("service_arguments", &transcription.service_arguments)?;
    dict.set_item("service_response", &transcription.service_response)?;
    dict.set_item("state", &transcription.state)?;
    dict.set_item("device_id", &transcription.device_id)?;
    dict.set_item("created_at", &transcription.created_at)?;
    dict.set_item("modified_at", &transcription.modified_at)?;
    dict.set_item("deleted_at", &transcription.deleted_at)?;
    Ok(dict)
}

fn hashmap_to_pydict<'py>(
    py: Python<'py>,
    map: &HashMap<String, serde_json::Value>,
) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    for (key, value) in map {
        dict.set_item(key, json_value_to_pyobject(py, value)?)?;
    }
    Ok(dict)
}

fn json_value_to_pyobject(py: Python<'_>, value: &serde_json::Value) -> PyResult<PyObject> {
    match value {
        serde_json::Value::Null => Ok(py.None()),
        serde_json::Value::Bool(b) => Ok(b.into_pyobject(py)?.to_owned().into_any().unbind()),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.into_pyobject(py)?.into_any().unbind())
            } else if let Some(f) = n.as_f64() {
                Ok(f.into_pyobject(py)?.into_any().unbind())
            } else {
                Ok(py.None())
            }
        }
        serde_json::Value::String(s) => Ok(s.into_pyobject(py)?.into_any().unbind()),
        serde_json::Value::Array(arr) => {
            let list = PyList::empty(py);
            for item in arr {
                list.append(json_value_to_pyobject(py, item)?)?;
            }
            Ok(list.into_any().unbind())
        }
        serde_json::Value::Object(obj) => {
            let dict = PyDict::new(py);
            for (k, v) in obj {
                dict.set_item(k, json_value_to_pyobject(py, v)?)?;
            }
            Ok(dict.into_any().unbind())
        }
    }
}

// ============================================================================
// Database wrapper
// ============================================================================

#[pyclass(name = "Database", unsendable)]
pub struct PyDatabase {
    inner: Option<database::Database>,
}

impl PyDatabase {
    fn inner_ref(&self) -> PyResult<&database::Database> {
        self.inner
            .as_ref()
            .ok_or_else(|| DatabaseError::new_err("Database has been closed"))
    }
}

#[pymethods]
impl PyDatabase {
    #[new]
    #[pyo3(signature = (db_path=None))]
    fn new(db_path: Option<&str>) -> PyResult<Self> {
        let db = match db_path {
            Some(path) => database::Database::new(path),
            None => database::Database::new_in_memory(),
        }
        .map_err(voice_error_to_pyerr)?;
        Ok(Self { inner: Some(db) })
    }

    fn close(&mut self) -> PyResult<()> {
        if let Some(db) = self.inner.take() {
            db.close().map_err(voice_error_to_pyerr)?;
        }
        Ok(())
    }

    fn create_note(&self, content: &str) -> PyResult<String> {
        self.inner_ref()?.create_note(content).map_err(voice_error_to_pyerr)
    }

    fn get_note<'py>(&self, py: Python<'py>, note_id: &str) -> PyResult<Option<PyObject>> {
        let note = self.inner_ref()?.get_note(note_id).map_err(voice_error_to_pyerr)?;
        match note {
            Some(n) => Ok(Some(note_row_to_dict(py, &n)?.into_any().unbind())),
            None => Ok(None),
        }
    }

    fn update_note(&self, note_id: &str, content: &str) -> PyResult<bool> {
        self.inner_ref()?.update_note(note_id, content).map_err(voice_error_to_pyerr)
    }

    fn delete_note(&self, note_id: &str) -> PyResult<bool> {
        self.inner_ref()?.delete_note(note_id).map_err(voice_error_to_pyerr)
    }

    fn get_all_notes<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let notes = self.inner_ref()?.get_all_notes().map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for note in &notes {
            list.append(note_row_to_dict(py, note)?)?;
        }
        Ok(list.into_any().unbind())
    }

    #[pyo3(signature = (name, parent_id=None))]
    fn create_tag(&self, name: &str, parent_id: Option<&str>) -> PyResult<String> {
        self.inner_ref()?.create_tag(name, parent_id).map_err(voice_error_to_pyerr)
    }

    fn get_tag<'py>(&self, py: Python<'py>, tag_id: &str) -> PyResult<Option<PyObject>> {
        let tag = self.inner_ref()?.get_tag(tag_id).map_err(voice_error_to_pyerr)?;
        match tag {
            Some(t) => Ok(Some(tag_row_to_dict(py, &t)?.into_any().unbind())),
            None => Ok(None),
        }
    }

    fn get_all_tags<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let tags = self.inner_ref()?.get_all_tags().map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for tag in &tags {
            list.append(tag_row_to_dict(py, tag)?)?;
        }
        Ok(list.into_any().unbind())
    }

    fn get_tags_by_name<'py>(&self, py: Python<'py>, name: &str) -> PyResult<PyObject> {
        let tags = self.inner_ref()?.get_tags_by_name(name).map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for tag in &tags {
            list.append(tag_row_to_dict(py, tag)?)?;
        }
        Ok(list.into_any().unbind())
    }

    fn get_tag_by_path<'py>(&self, py: Python<'py>, path: &str) -> PyResult<Option<PyObject>> {
        let tag = self.inner_ref()?.get_tag_by_path(path).map_err(voice_error_to_pyerr)?;
        match tag {
            Some(t) => Ok(Some(tag_row_to_dict(py, &t)?.into_any().unbind())),
            None => Ok(None),
        }
    }

    fn get_all_tags_by_path<'py>(&self, py: Python<'py>, path: &str) -> PyResult<PyObject> {
        let tags = self.inner_ref()?.get_all_tags_by_path(path).map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for tag in &tags {
            list.append(tag_row_to_dict(py, tag)?)?;
        }
        Ok(list.into_any().unbind())
    }

    fn is_tag_name_ambiguous(&self, name: &str) -> PyResult<bool> {
        self.inner_ref()?.is_tag_name_ambiguous(name).map_err(voice_error_to_pyerr)
    }

    fn get_tag_descendants<'py>(&self, py: Python<'py>, tag_id: &str) -> PyResult<PyObject> {
        let descendants = self.inner_ref()?.get_tag_descendants(tag_id).map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for id_bytes in &descendants {
            // Convert bytes to hex string
            let hex: String = id_bytes.iter().map(|b| format!("{:02x}", b)).collect();
            list.append(hex)?;
        }
        Ok(list.into_any().unbind())
    }

    fn rename_tag(&self, tag_id: &str, new_name: &str) -> PyResult<bool> {
        self.inner_ref()?.rename_tag(tag_id, new_name).map_err(voice_error_to_pyerr)
    }

    fn delete_tag(&self, tag_id: &str) -> PyResult<bool> {
        self.inner_ref()?.delete_tag(tag_id).map_err(voice_error_to_pyerr)
    }

    fn add_tag_to_note(&self, note_id: &str, tag_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .add_tag_to_note(note_id, tag_id)
            .map_err(voice_error_to_pyerr)
    }

    fn remove_tag_from_note(&self, note_id: &str, tag_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .remove_tag_from_note(note_id, tag_id)
            .map_err(voice_error_to_pyerr)
    }

    fn get_note_tags<'py>(&self, py: Python<'py>, note_id: &str) -> PyResult<PyObject> {
        let tags = self.inner_ref()?.get_note_tags(note_id).map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for tag in &tags {
            list.append(tag_row_to_dict(py, tag)?)?;
        }
        Ok(list.into_any().unbind())
    }

    fn filter_notes<'py>(&self, py: Python<'py>, tag_ids: Vec<String>) -> PyResult<PyObject> {
        let notes = self.inner_ref()?.filter_notes(&tag_ids).map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for note in &notes {
            list.append(note_row_to_dict(py, note)?)?;
        }
        Ok(list.into_any().unbind())
    }

    #[pyo3(signature = (text_query=None, tag_id_groups=None))]
    fn search_notes<'py>(
        &self,
        py: Python<'py>,
        text_query: Option<&str>,
        tag_id_groups: Option<Vec<Vec<String>>>,
    ) -> PyResult<PyObject> {
        let groups_ref = tag_id_groups.as_ref();
        let notes = self
            .inner_ref()?
            .search_notes(text_query, groups_ref)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for note in &notes {
            list.append(note_row_to_dict(py, note)?)?;
        }
        Ok(list.into_any().unbind())
    }

    // ========================================================================
    // Sync methods
    // ========================================================================

    fn get_peer_last_sync(&self, peer_device_id: &str) -> PyResult<Option<String>> {
        self.inner_ref()?
            .get_peer_last_sync(peer_device_id)
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (peer_device_id, peer_name=None))]
    fn update_peer_sync_time(&self, peer_device_id: &str, peer_name: Option<&str>) -> PyResult<()> {
        self.inner_ref()?
            .update_peer_sync_time(peer_device_id, peer_name)
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (since=None, limit=1000))]
    fn get_changes_since<'py>(
        &self,
        py: Python<'py>,
        since: Option<&str>,
        limit: i64,
    ) -> PyResult<PyObject> {
        let (changes, latest) = self
            .inner_ref()?
            .get_changes_since(since, limit)
            .map_err(voice_error_to_pyerr)?;

        let result = PyDict::new(py);
        let changes_list = PyList::empty(py);
        for change in &changes {
            changes_list.append(hashmap_to_pydict(py, change)?)?;
        }
        result.set_item("changes", changes_list)?;
        result.set_item("latest_timestamp", latest)?;
        Ok(result.into_any().unbind())
    }

    fn get_full_dataset<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let dataset = self.inner_ref()?.get_full_dataset().map_err(voice_error_to_pyerr)?;

        let result = PyDict::new(py);
        for (key, items) in &dataset {
            let list = PyList::empty(py);
            for item in items {
                list.append(hashmap_to_pydict(py, item)?)?;
            }
            result.set_item(key, list)?;
        }
        Ok(result.into_any().unbind())
    }

    // ========================================================================
    // Sync apply methods
    // ========================================================================

    #[pyo3(signature = (note_id, created_at, content, modified_at=None, deleted_at=None))]
    fn apply_sync_note(
        &self,
        note_id: &str,
        created_at: &str,
        content: &str,
        modified_at: Option<&str>,
        deleted_at: Option<&str>,
    ) -> PyResult<bool> {
        self.inner_ref()?
            .apply_sync_note(note_id, created_at, content, modified_at, deleted_at)
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (tag_id, name, parent_id, created_at, modified_at=None))]
    fn apply_sync_tag(
        &self,
        tag_id: &str,
        name: &str,
        parent_id: Option<&str>,
        created_at: &str,
        modified_at: Option<&str>,
    ) -> PyResult<bool> {
        self.inner_ref()?
            .apply_sync_tag(tag_id, name, parent_id, created_at, modified_at)
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (note_id, tag_id, created_at, modified_at=None, deleted_at=None))]
    fn apply_sync_note_tag(
        &self,
        note_id: &str,
        tag_id: &str,
        created_at: &str,
        modified_at: Option<&str>,
        deleted_at: Option<&str>,
    ) -> PyResult<bool> {
        self.inner_ref()?
            .apply_sync_note_tag(note_id, tag_id, created_at, modified_at, deleted_at)
            .map_err(voice_error_to_pyerr)
    }

    // ========================================================================
    // Raw data methods (for sync)
    // ========================================================================

    fn get_note_raw<'py>(&self, py: Python<'py>, note_id: &str) -> PyResult<Option<PyObject>> {
        let note = self.inner_ref()?.get_note_raw(note_id).map_err(voice_error_to_pyerr)?;
        match note {
            Some(n) => Ok(Some(hashmap_to_pydict(py, &n)?.into_any().unbind())),
            None => Ok(None),
        }
    }

    fn get_tag_raw<'py>(&self, py: Python<'py>, tag_id: &str) -> PyResult<Option<PyObject>> {
        let tag = self.inner_ref()?.get_tag_raw(tag_id).map_err(voice_error_to_pyerr)?;
        match tag {
            Some(t) => Ok(Some(hashmap_to_pydict(py, &t)?.into_any().unbind())),
            None => Ok(None),
        }
    }

    fn get_note_tag_raw<'py>(
        &self,
        py: Python<'py>,
        note_id: &str,
        tag_id: &str,
    ) -> PyResult<Option<PyObject>> {
        let nt = self
            .inner_ref()?
            .get_note_tag_raw(note_id, tag_id)
            .map_err(voice_error_to_pyerr)?;
        match nt {
            Some(n) => Ok(Some(hashmap_to_pydict(py, &n)?.into_any().unbind())),
            None => Ok(None),
        }
    }

    // ========================================================================
    // Conflict creation methods
    // ========================================================================

    #[pyo3(signature = (note_id, local_content, local_modified_at, remote_content, remote_modified_at, remote_device_id=None, remote_device_name=None))]
    fn create_note_content_conflict(
        &self,
        note_id: &str,
        local_content: &str,
        local_modified_at: &str,
        remote_content: &str,
        remote_modified_at: &str,
        remote_device_id: Option<&str>,
        remote_device_name: Option<&str>,
    ) -> PyResult<String> {
        self.inner_ref()?
            .create_note_content_conflict(
                note_id,
                local_content,
                local_modified_at,
                remote_content,
                remote_modified_at,
                remote_device_id,
                remote_device_name,
            )
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (note_id, surviving_content, surviving_modified_at, surviving_device_id, deleted_content, deleted_at, deleting_device_id=None, deleting_device_name=None))]
    fn create_note_delete_conflict(
        &self,
        note_id: &str,
        surviving_content: &str,
        surviving_modified_at: &str,
        surviving_device_id: Option<&str>,
        deleted_content: Option<&str>,
        deleted_at: &str,
        deleting_device_id: Option<&str>,
        deleting_device_name: Option<&str>,
    ) -> PyResult<String> {
        self.inner_ref()?
            .create_note_delete_conflict(
                note_id,
                surviving_content,
                surviving_modified_at,
                surviving_device_id,
                deleted_content,
                deleted_at,
                deleting_device_id,
                deleting_device_name,
            )
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (tag_id, local_name, local_modified_at, remote_name, remote_modified_at, remote_device_id=None, remote_device_name=None))]
    fn create_tag_rename_conflict(
        &self,
        tag_id: &str,
        local_name: &str,
        local_modified_at: &str,
        remote_name: &str,
        remote_modified_at: &str,
        remote_device_id: Option<&str>,
        remote_device_name: Option<&str>,
    ) -> PyResult<String> {
        self.inner_ref()?
            .create_tag_rename_conflict(
                tag_id,
                local_name,
                local_modified_at,
                remote_name,
                remote_modified_at,
                remote_device_id,
                remote_device_name,
            )
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (note_id, tag_id, local_created_at=None, local_modified_at=None, local_deleted_at=None, remote_created_at=None, remote_modified_at=None, remote_deleted_at=None, remote_device_id=None, remote_device_name=None))]
    fn create_note_tag_conflict(
        &self,
        note_id: &str,
        tag_id: &str,
        local_created_at: Option<&str>,
        local_modified_at: Option<&str>,
        local_deleted_at: Option<&str>,
        remote_created_at: Option<&str>,
        remote_modified_at: Option<&str>,
        remote_deleted_at: Option<&str>,
        remote_device_id: Option<&str>,
        remote_device_name: Option<&str>,
    ) -> PyResult<String> {
        self.inner_ref()?
            .create_note_tag_conflict(
                note_id,
                tag_id,
                local_created_at,
                local_modified_at,
                local_deleted_at,
                remote_created_at,
                remote_modified_at,
                remote_deleted_at,
                remote_device_id,
                remote_device_name,
            )
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (tag_id, local_parent_id, local_modified_at, remote_parent_id, remote_modified_at, remote_device_id=None, remote_device_name=None))]
    fn create_tag_parent_conflict(
        &self,
        tag_id: &str,
        local_parent_id: Option<&str>,
        local_modified_at: &str,
        remote_parent_id: Option<&str>,
        remote_modified_at: &str,
        remote_device_id: Option<&str>,
        remote_device_name: Option<&str>,
    ) -> PyResult<String> {
        self.inner_ref()?
            .create_tag_parent_conflict(
                tag_id,
                local_parent_id,
                local_modified_at,
                remote_parent_id,
                remote_modified_at,
                remote_device_id,
                remote_device_name,
            )
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (tag_id, surviving_name, surviving_parent_id, surviving_modified_at, surviving_device_id=None, surviving_device_name=None, deleted_at=None, deleting_device_id=None, deleting_device_name=None))]
    fn create_tag_delete_conflict(
        &self,
        tag_id: &str,
        surviving_name: &str,
        surviving_parent_id: Option<&str>,
        surviving_modified_at: &str,
        surviving_device_id: Option<&str>,
        surviving_device_name: Option<&str>,
        deleted_at: Option<&str>,
        deleting_device_id: Option<&str>,
        deleting_device_name: Option<&str>,
    ) -> PyResult<String> {
        self.inner_ref()?
            .create_tag_delete_conflict(
                tag_id,
                surviving_name,
                surviving_parent_id,
                surviving_modified_at,
                surviving_device_id,
                surviving_device_name,
                deleted_at.unwrap_or(""),
                deleting_device_id,
                deleting_device_name,
            )
            .map_err(voice_error_to_pyerr)
    }

    // ========================================================================
    // Conflict query methods
    // ========================================================================

    fn get_unresolved_conflict_counts<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let counts = self
            .inner_ref()?
            .get_unresolved_conflict_counts()
            .map_err(voice_error_to_pyerr)?;
        let dict = PyDict::new(py);
        for (key, value) in &counts {
            dict.set_item(key, value)?;
        }
        Ok(dict.into_any().unbind())
    }

    #[pyo3(signature = (include_resolved=false))]
    fn get_note_content_conflicts<'py>(
        &self,
        py: Python<'py>,
        include_resolved: bool,
    ) -> PyResult<PyObject> {
        let conflicts = self
            .inner_ref()?
            .get_note_content_conflicts(include_resolved)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for conflict in &conflicts {
            list.append(hashmap_to_pydict(py, conflict)?)?;
        }
        Ok(list.into_any().unbind())
    }

    #[pyo3(signature = (include_resolved=false))]
    fn get_note_delete_conflicts<'py>(
        &self,
        py: Python<'py>,
        include_resolved: bool,
    ) -> PyResult<PyObject> {
        let conflicts = self
            .inner_ref()?
            .get_note_delete_conflicts(include_resolved)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for conflict in &conflicts {
            list.append(hashmap_to_pydict(py, conflict)?)?;
        }
        Ok(list.into_any().unbind())
    }

    #[pyo3(signature = (include_resolved=false))]
    fn get_tag_rename_conflicts<'py>(
        &self,
        py: Python<'py>,
        include_resolved: bool,
    ) -> PyResult<PyObject> {
        let conflicts = self
            .inner_ref()?
            .get_tag_rename_conflicts(include_resolved)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for conflict in &conflicts {
            list.append(hashmap_to_pydict(py, conflict)?)?;
        }
        Ok(list.into_any().unbind())
    }

    #[pyo3(signature = (include_resolved=false))]
    fn get_tag_parent_conflicts<'py>(
        &self,
        py: Python<'py>,
        include_resolved: bool,
    ) -> PyResult<PyObject> {
        let conflicts = self
            .inner_ref()?
            .get_tag_parent_conflicts(include_resolved)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for conflict in &conflicts {
            list.append(hashmap_to_pydict(py, conflict)?)?;
        }
        Ok(list.into_any().unbind())
    }

    #[pyo3(signature = (include_resolved=false))]
    fn get_tag_delete_conflicts<'py>(
        &self,
        py: Python<'py>,
        include_resolved: bool,
    ) -> PyResult<PyObject> {
        let conflicts = self
            .inner_ref()?
            .get_tag_delete_conflicts(include_resolved)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for conflict in &conflicts {
            list.append(hashmap_to_pydict(py, conflict)?)?;
        }
        Ok(list.into_any().unbind())
    }

    // ========================================================================
    // Conflict resolution methods
    // ========================================================================

    fn resolve_note_content_conflict(&self, conflict_id: &str, new_content: &str) -> PyResult<bool> {
        self.inner_ref()?
            .resolve_note_content_conflict(conflict_id, new_content)
            .map_err(voice_error_to_pyerr)
    }

    fn resolve_note_delete_conflict(&self, conflict_id: &str, restore_note: bool) -> PyResult<bool> {
        self.inner_ref()?
            .resolve_note_delete_conflict(conflict_id, restore_note)
            .map_err(voice_error_to_pyerr)
    }

    fn resolve_tag_rename_conflict(&self, conflict_id: &str, new_name: &str) -> PyResult<bool> {
        self.inner_ref()?
            .resolve_tag_rename_conflict(conflict_id, new_name)
            .map_err(voice_error_to_pyerr)
    }

    // ========================================================================
    // NoteAttachment methods
    // ========================================================================

    fn attach_to_note(&self, note_id: &str, attachment_id: &str, attachment_type: &str) -> PyResult<String> {
        self.inner_ref()?
            .attach_to_note(note_id, attachment_id, attachment_type)
            .map_err(voice_error_to_pyerr)
    }

    fn detach_from_note(&self, association_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .detach_from_note(association_id)
            .map_err(voice_error_to_pyerr)
    }

    fn get_attachments_for_note<'py>(&self, py: Python<'py>, note_id: &str) -> PyResult<PyObject> {
        let attachments = self.inner_ref()?
            .get_attachments_for_note(note_id)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for attachment in &attachments {
            list.append(note_attachment_row_to_dict(py, attachment)?)?;
        }
        Ok(list.into_any().unbind())
    }

    fn get_attachment<'py>(&self, py: Python<'py>, association_id: &str) -> PyResult<Option<PyObject>> {
        let attachment = self.inner_ref()?
            .get_attachment(association_id)
            .map_err(voice_error_to_pyerr)?;
        match attachment {
            Some(a) => Ok(Some(note_attachment_row_to_dict(py, &a)?.into_any().unbind())),
            None => Ok(None),
        }
    }

    fn get_note_attachment_raw<'py>(&self, py: Python<'py>, association_id: &str) -> PyResult<Option<PyObject>> {
        let attachment = self.inner_ref()?
            .get_note_attachment_raw(association_id)
            .map_err(voice_error_to_pyerr)?;
        match attachment {
            Some(a) => Ok(Some(json_value_to_pyobject(py, &a)?)),
            None => Ok(None),
        }
    }

    #[pyo3(signature = (id, note_id, attachment_id, attachment_type, created_at, modified_at=None, deleted_at=None))]
    fn apply_sync_note_attachment(
        &self,
        id: &str,
        note_id: &str,
        attachment_id: &str,
        attachment_type: &str,
        created_at: &str,
        modified_at: Option<&str>,
        deleted_at: Option<&str>,
    ) -> PyResult<()> {
        self.inner_ref()?
            .apply_sync_note_attachment(id, note_id, attachment_id, attachment_type, created_at, modified_at, deleted_at)
            .map_err(voice_error_to_pyerr)
    }

    // ========================================================================
    // AudioFile methods
    // ========================================================================

    #[pyo3(signature = (filename, file_created_at=None))]
    fn create_audio_file(&self, filename: &str, file_created_at: Option<&str>) -> PyResult<String> {
        self.inner_ref()?
            .create_audio_file(filename, file_created_at)
            .map_err(voice_error_to_pyerr)
    }

    fn get_audio_file<'py>(&self, py: Python<'py>, audio_file_id: &str) -> PyResult<Option<PyObject>> {
        let audio_file = self.inner_ref()?
            .get_audio_file(audio_file_id)
            .map_err(voice_error_to_pyerr)?;
        match audio_file {
            Some(af) => Ok(Some(audio_file_row_to_dict(py, &af)?.into_any().unbind())),
            None => Ok(None),
        }
    }

    fn get_audio_files_for_note<'py>(&self, py: Python<'py>, note_id: &str) -> PyResult<PyObject> {
        let audio_files = self.inner_ref()?
            .get_audio_files_for_note(note_id)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for audio_file in &audio_files {
            list.append(audio_file_row_to_dict(py, audio_file)?)?;
        }
        Ok(list.into_any().unbind())
    }

    fn get_all_audio_files<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let audio_files = self.inner_ref()?
            .get_all_audio_files()
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for audio_file in &audio_files {
            list.append(audio_file_row_to_dict(py, audio_file)?)?;
        }
        Ok(list.into_any().unbind())
    }

    fn update_audio_file_summary(&self, audio_file_id: &str, summary: &str) -> PyResult<bool> {
        self.inner_ref()?
            .update_audio_file_summary(audio_file_id, summary)
            .map_err(voice_error_to_pyerr)
    }

    fn delete_audio_file(&self, audio_file_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .delete_audio_file(audio_file_id)
            .map_err(voice_error_to_pyerr)
    }

    fn get_audio_file_raw<'py>(&self, py: Python<'py>, audio_file_id: &str) -> PyResult<Option<PyObject>> {
        let audio_file = self.inner_ref()?
            .get_audio_file_raw(audio_file_id)
            .map_err(voice_error_to_pyerr)?;
        match audio_file {
            Some(af) => Ok(Some(json_value_to_pyobject(py, &af)?)),
            None => Ok(None),
        }
    }

    #[pyo3(signature = (id, imported_at, filename, file_created_at=None, summary=None, modified_at=None, deleted_at=None))]
    fn apply_sync_audio_file(
        &self,
        id: &str,
        imported_at: &str,
        filename: &str,
        file_created_at: Option<&str>,
        summary: Option<&str>,
        modified_at: Option<&str>,
        deleted_at: Option<&str>,
    ) -> PyResult<()> {
        self.inner_ref()?
            .apply_sync_audio_file(id, imported_at, filename, file_created_at, summary, modified_at, deleted_at)
            .map_err(voice_error_to_pyerr)
    }

    // ========================================================================
    // Transcription methods
    // ========================================================================

    #[pyo3(signature = (audio_file_id, content, service, content_segments=None, service_arguments=None, service_response=None, state=None))]
    fn create_transcription(
        &self,
        audio_file_id: &str,
        content: &str,
        service: &str,
        content_segments: Option<&str>,
        service_arguments: Option<&str>,
        service_response: Option<&str>,
        state: Option<&str>,
    ) -> PyResult<String> {
        self.inner_ref()?
            .create_transcription(
                audio_file_id,
                content,
                content_segments,
                service,
                service_arguments,
                service_response,
                state,
            )
            .map_err(voice_error_to_pyerr)
    }

    fn get_transcription<'py>(&self, py: Python<'py>, transcription_id: &str) -> PyResult<Option<PyObject>> {
        let transcription = self.inner_ref()?
            .get_transcription(transcription_id)
            .map_err(voice_error_to_pyerr)?;
        match transcription {
            Some(t) => Ok(Some(transcription_row_to_dict(py, &t)?.into_any().unbind())),
            None => Ok(None),
        }
    }

    fn get_transcriptions_for_audio_file<'py>(&self, py: Python<'py>, audio_file_id: &str) -> PyResult<PyObject> {
        let transcriptions = self.inner_ref()?
            .get_transcriptions_for_audio_file(audio_file_id)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for transcription in &transcriptions {
            list.append(transcription_row_to_dict(py, transcription)?)?;
        }
        Ok(list.into_any().unbind())
    }

    fn delete_transcription(&self, transcription_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .delete_transcription(transcription_id)
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (transcription_id, content, content_segments=None, service_response=None, state=None))]
    fn update_transcription(
        &self,
        transcription_id: &str,
        content: &str,
        content_segments: Option<&str>,
        service_response: Option<&str>,
        state: Option<&str>,
    ) -> PyResult<bool> {
        self.inner_ref()?
            .update_transcription(transcription_id, content, content_segments, service_response, state)
            .map_err(voice_error_to_pyerr)
    }

    // ========================================================================
    // Maintenance methods
    // ========================================================================

    /// Normalize database data for consistency.
    ///
    /// This runs various normalization passes:
    /// - Timestamp normalization (ISO 8601 -> SQLite format)
    /// - (Future: Unicode normalization, etc.)
    fn normalize_database(&mut self) -> PyResult<()> {
        self.inner
            .as_mut()
            .ok_or_else(|| DatabaseError::new_err("Database has been closed"))?
            .normalize_database()
            .map_err(voice_error_to_pyerr)
    }
}

// ============================================================================
// Config wrapper
// ============================================================================

#[pyclass(name = "Config")]
pub struct PyConfig {
    inner: std::sync::Mutex<config::Config>,
}

#[pymethods]
impl PyConfig {
    #[new]
    #[pyo3(signature = (config_dir=None))]
    fn new(config_dir: Option<&str>) -> PyResult<Self> {
        let path = config_dir.map(std::path::PathBuf::from);
        let cfg = config::Config::new(path).map_err(voice_error_to_pyerr)?;
        Ok(Self {
            inner: std::sync::Mutex::new(cfg),
        })
    }

    fn get_config_dir(&self) -> PyResult<String> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.config_dir().to_string_lossy().to_string())
    }

    fn get_device_id_hex(&self) -> PyResult<String> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.device_id_hex().to_string())
    }

    fn get_device_name(&self) -> PyResult<String> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.device_name().to_string())
    }

    fn get_database_file(&self) -> PyResult<String> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.database_file().to_string())
    }

    fn is_sync_enabled(&self) -> PyResult<bool> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.is_sync_enabled())
    }

    fn set_sync_enabled(&self, enabled: bool) -> PyResult<()> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.set_sync_enabled(enabled).map_err(voice_error_to_pyerr)
    }

    fn get_sync_server_port(&self) -> PyResult<u16> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.sync_server_port())
    }

    fn set_sync_server_port(&self, port: u16) -> PyResult<()> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.set_sync_server_port(port).map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (key, default=None))]
    fn get(&self, key: &str, default: Option<&str>) -> PyResult<Option<String>> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.get(key).or_else(|| default.map(String::from)))
    }

    fn set(&self, key: &str, value: &str) -> PyResult<()> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.set(key, value).map_err(voice_error_to_pyerr)
    }

    fn get_peers<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let cfg = self.inner.lock().unwrap();
        let list = PyList::empty(py);
        for peer in cfg.peers() {
            let dict = PyDict::new(py);
            dict.set_item("peer_id", &peer.peer_id)?;
            dict.set_item("peer_name", &peer.peer_name)?;
            dict.set_item("peer_url", &peer.peer_url)?;
            dict.set_item("certificate_fingerprint", &peer.certificate_fingerprint)?;
            list.append(dict)?;
        }
        Ok(list.into_any().unbind())
    }

    fn get_peer<'py>(&self, py: Python<'py>, peer_id: &str) -> PyResult<Option<PyObject>> {
        let cfg = self.inner.lock().unwrap();
        match cfg.get_peer(peer_id) {
            Some(peer) => {
                let dict = PyDict::new(py);
                dict.set_item("peer_id", &peer.peer_id)?;
                dict.set_item("peer_name", &peer.peer_name)?;
                dict.set_item("peer_url", &peer.peer_url)?;
                dict.set_item("certificate_fingerprint", &peer.certificate_fingerprint)?;
                Ok(Some(dict.into_any().unbind()))
            }
            None => Ok(None),
        }
    }

    #[pyo3(signature = (peer_id, peer_name, peer_url, certificate_fingerprint=None, allow_update=true))]
    fn add_peer(
        &self,
        peer_id: &str,
        peer_name: &str,
        peer_url: &str,
        certificate_fingerprint: Option<&str>,
        allow_update: bool,
    ) -> PyResult<()> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.add_peer(
            peer_id,
            peer_name,
            peer_url,
            certificate_fingerprint,
            allow_update,
        )
        .map_err(voice_error_to_pyerr)
    }

    fn remove_peer(&self, peer_id: &str) -> PyResult<bool> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.remove_peer(peer_id).map_err(voice_error_to_pyerr)
    }

    fn update_peer_certificate(&self, peer_id: &str, fingerprint: &str) -> PyResult<bool> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.update_peer_certificate(peer_id, fingerprint)
            .map_err(voice_error_to_pyerr)
    }

    fn get_certs_dir(&self) -> PyResult<String> {
        let cfg = self.inner.lock().unwrap();
        let path = cfg.certs_dir().map_err(voice_error_to_pyerr)?;
        Ok(path.to_string_lossy().to_string())
    }

    fn get_tui_colors<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let cfg = self.inner.lock().unwrap();
        let (focused, unfocused) = cfg.tui_colors();
        let dict = PyDict::new(py);
        dict.set_item("focused", focused)?;
        dict.set_item("unfocused", unfocused)?;
        Ok(dict.into_any().unbind())
    }

    fn get_warning_color(&self, theme: &str) -> PyResult<String> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.warning_color(theme).to_string())
    }

    fn set_device_name(&self, name: &str) -> PyResult<()> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.set_device_name(name).map_err(voice_error_to_pyerr)
    }

    fn get_audiofile_directory(&self) -> PyResult<Option<String>> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.audiofile_directory().map(|s| s.to_string()))
    }

    fn set_audiofile_directory(&self, path: &str) -> PyResult<()> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.set_audiofile_directory(path).map_err(voice_error_to_pyerr)
    }

    fn clear_audiofile_directory(&self) -> PyResult<()> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.clear_audiofile_directory().map_err(voice_error_to_pyerr)
    }

    fn get_audiofile_trash_directory(&self) -> PyResult<Option<String>> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.audiofile_trash_directory().map(|p| p.to_string_lossy().to_string()))
    }

    fn get_sync_config<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let cfg = self.inner.lock().unwrap();
        let sync_cfg = cfg.sync_config();
        let dict = PyDict::new(py);
        dict.set_item("enabled", sync_cfg.enabled)?;
        dict.set_item("server_port", sync_cfg.server_port)?;
        let peers_list = PyList::empty(py);
        for peer in &sync_cfg.peers {
            let peer_dict = PyDict::new(py);
            peer_dict.set_item("peer_id", &peer.peer_id)?;
            peer_dict.set_item("peer_name", &peer.peer_name)?;
            peer_dict.set_item("peer_url", &peer.peer_url)?;
            peer_dict.set_item("certificate_fingerprint", &peer.certificate_fingerprint)?;
            peers_list.append(peer_dict)?;
        }
        dict.set_item("peers", peers_list)?;
        Ok(dict.into_any().unbind())
    }

    // ========================================================================
    // Transcription config methods (generic JSON access)
    // ========================================================================

    /// Get transcription configuration as a Python dict.
    /// Voicecore stores this data but doesn't interpret it - the transcription
    /// module is responsible for understanding the structure.
    fn get_transcription_config<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let cfg = self.inner.lock().unwrap();
        let json_value = cfg.transcription_json();
        json_value_to_pyobject(py, json_value)
    }

    /// Set transcription configuration from a Python dict.
    fn set_transcription_config(&self, py: Python<'_>, value: PyObject) -> PyResult<()> {
        let json_value = pyobject_to_json_value(py, &value)?;
        let mut cfg = self.inner.lock().unwrap();
        cfg.set_transcription_json(json_value).map_err(voice_error_to_pyerr)
    }
}

// ============================================================================
// Sync client wrappers
// ============================================================================

/// Result of a sync operation
#[pyclass(name = "SyncResult")]
pub struct PySyncResult {
    #[pyo3(get)]
    success: bool,
    #[pyo3(get)]
    pulled: i64,
    #[pyo3(get)]
    pushed: i64,
    #[pyo3(get)]
    conflicts: i64,
    #[pyo3(get)]
    errors: Vec<String>,
}

impl From<sync_client::SyncResult> for PySyncResult {
    fn from(result: sync_client::SyncResult) -> Self {
        Self {
            success: result.success,
            pulled: result.pulled,
            pushed: result.pushed,
            conflicts: result.conflicts,
            errors: result.errors,
        }
    }
}

/// Sync client for synchronizing with peers
#[pyclass(name = "SyncClient", unsendable)]
pub struct PySyncClient {
    inner: sync_client::SyncClient,
    runtime: tokio::runtime::Runtime,
}

#[pymethods]
impl PySyncClient {
    /// Create a new sync client.
    ///
    /// Args:
    ///     config_dir: Path to config directory (optional, uses default if None)
    ///
    /// The sync client creates its own database connection from the config.
    #[new]
    #[pyo3(signature = (config_dir=None))]
    fn new(config_dir: Option<&str>) -> PyResult<Self> {
        // Create Tokio runtime for blocking async calls
        let runtime = tokio::runtime::Runtime::new()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        // Create Config from config_dir
        let config_path = config_dir.map(std::path::PathBuf::from);
        let cfg = config::Config::new(config_path).map_err(voice_error_to_pyerr)?;

        // Create Database from config's database_file path
        let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;

        // Wrap in Arc<Mutex<>> for SyncClient
        let db_arc = Arc::new(Mutex::new(db));
        let config_arc = Arc::new(Mutex::new(cfg));

        let inner = sync_client::SyncClient::new(db_arc, config_arc)
            .map_err(voice_error_to_pyerr)?;

        Ok(Self { inner, runtime })
    }

    /// Perform full bidirectional sync with a peer
    fn sync_with_peer(&self, peer_id: &str) -> PyResult<PySyncResult> {
        let result = self.runtime.block_on(self.inner.sync_with_peer(peer_id));
        Ok(PySyncResult::from(result))
    }

    /// Pull changes from a peer (one-way)
    fn pull_from_peer(&self, peer_id: &str) -> PyResult<PySyncResult> {
        let result = self.runtime.block_on(self.inner.pull_from_peer(peer_id));
        Ok(PySyncResult::from(result))
    }

    /// Push changes to a peer (one-way)
    fn push_to_peer(&self, peer_id: &str) -> PyResult<PySyncResult> {
        let result = self.runtime.block_on(self.inner.push_to_peer(peer_id));
        Ok(PySyncResult::from(result))
    }

    /// Perform initial sync (full dataset transfer) with a peer
    fn initial_sync(&self, peer_id: &str) -> PyResult<PySyncResult> {
        let result = self.runtime.block_on(self.inner.initial_sync(peer_id));
        Ok(PySyncResult::from(result))
    }

    /// Check if a peer is reachable
    fn check_peer_status<'py>(&self, py: Python<'py>, peer_id: &str) -> PyResult<PyObject> {
        let result = self.runtime.block_on(self.inner.check_peer_status(peer_id));
        let dict = PyDict::new(py);
        for (key, value) in result {
            dict.set_item(key, json_value_to_pyobject(py, &value)?)?;
        }
        Ok(dict.into_any().unbind())
    }

    /// Download an audio file from a peer
    /// Returns a dict with {"success": bool, "bytes": int} or {"success": false, "error": str}
    fn download_audio_file(&self, py: Python<'_>, peer_url: &str, audio_id: &str, dest_path: &str) -> PyResult<PyObject> {
        let dest = std::path::Path::new(dest_path);
        let result = self.runtime.block_on(
            self.inner.download_audio_file(peer_url, audio_id, dest)
        );
        let dict = PyDict::new(py);
        match result {
            Ok(bytes) => {
                dict.set_item("success", true)?;
                dict.set_item("bytes", bytes)?;
            }
            Err(e) => {
                dict.set_item("success", false)?;
                dict.set_item("error", format!("{}", e))?;
            }
        }
        Ok(dict.into_any().unbind())
    }

    /// Upload an audio file to a peer
    /// Returns a dict with {"success": bool, "bytes": int} or {"success": false, "error": str}
    fn upload_audio_file(&self, py: Python<'_>, peer_url: &str, audio_id: &str, source_path: &str) -> PyResult<PyObject> {
        let source = std::path::Path::new(source_path);
        let result = self.runtime.block_on(
            self.inner.upload_audio_file(peer_url, audio_id, source)
        );
        let dict = PyDict::new(py);
        match result {
            Ok(bytes) => {
                dict.set_item("success", true)?;
                dict.set_item("bytes", bytes)?;
            }
            Err(e) => {
                dict.set_item("success", false)?;
                dict.set_item("error", format!("{}", e))?;
            }
        }
        Ok(dict.into_any().unbind())
    }

    /// Debug method to see what changes would be pushed for a peer
    fn debug_get_changes(&self, peer_id: &str, since: Option<&str>) -> PyResult<Vec<String>> {
        // Get local last_sync for peer
        let local_last_sync = self.inner.debug_get_local_last_sync(peer_id);
        let effective_since = since.or(local_last_sync.as_deref());

        // Get changes since that timestamp
        let changes = self.inner.debug_get_changes_since(effective_since)
            .map_err(voice_error_to_pyerr)?;

        // Return a summary of each change
        let mut result = vec![
            format!("local_last_sync for {}: {:?}", peer_id, local_last_sync),
            format!("effective_since: {:?}", effective_since),
            format!("changes found: {}", changes.len()),
        ];
        for c in changes.iter().take(5) {
            result.push(format!("  {} {} {} ts={}", c.entity_type, c.operation, c.entity_id, c.timestamp));
        }
        Ok(result)
    }
}

/// Sync with all configured peers
///
/// Args:
///     config_dir: Path to config directory (optional, uses default if None)
///
/// Returns:
///     Dict mapping peer_id to SyncResult
#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn sync_all_peers<'py>(
    py: Python<'py>,
    config_dir: Option<&str>,
) -> PyResult<PyObject> {
    // Create Tokio runtime
    let runtime = tokio::runtime::Runtime::new()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    // Create Config and Database from config_dir
    let config_path = config_dir.map(std::path::PathBuf::from);
    let cfg = config::Config::new(config_path).map_err(voice_error_to_pyerr)?;
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;

    // Wrap in Arc<Mutex<>> for sync_all_peers
    let db_arc = Arc::new(Mutex::new(db));
    let config_arc = Arc::new(Mutex::new(cfg));

    // Run sync
    let results = runtime.block_on(sync_client::sync_all_peers(db_arc, config_arc));

    // Convert to Python dict
    let dict = PyDict::new(py);
    for (peer_id, result) in results {
        let py_result = PySyncResult::from(result);
        dict.set_item(peer_id, py_result.into_pyobject(py)?)?;
    }
    Ok(dict.into_any().unbind())
}

// ============================================================================
// Sync server wrappers
// ============================================================================

/// Start the sync server (blocking).
///
/// This function blocks until the server is stopped (via stop_sync_server or Ctrl+C).
///
/// Args:
///     config_dir: Path to config directory (optional, uses default if None)
///     port: Port to listen on (optional, uses config default if None)
///     verbose: Enable verbose logging to stdout (default: False)
///     ansi_colors: Enable ANSI color codes in log output (default: True)
#[pyfunction]
#[pyo3(signature = (config_dir=None, port=None, verbose=false, ansi_colors=true))]
fn start_sync_server(
    config_dir: Option<&str>,
    port: Option<u16>,
    verbose: bool,
    ansi_colors: bool,
) -> PyResult<()> {
    // Initialize tracing subscriber for logging output only if verbose is enabled
    if verbose {
        use tracing_subscriber::fmt;
        let builder = fmt()
            .with_max_level(tracing_subscriber::filter::LevelFilter::INFO)
            .with_target(false)
            .with_ansi(ansi_colors);
        let _ = builder.try_init();
    }

    // Create Tokio runtime
    let runtime = tokio::runtime::Runtime::new()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    // Create Config and Database from config_dir
    let config_path = config_dir.map(std::path::PathBuf::from);
    let cfg = config::Config::new(config_path).map_err(voice_error_to_pyerr)?;
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;

    // Get port from config if not specified
    let server_port = port.unwrap_or_else(|| cfg.sync_server_port());

    // Print server info
    println!("Starting Rust sync server...");
    println!("  Device ID:   {}", cfg.device_id_hex());
    println!("  Device Name: {}", cfg.device_name());
    println!("  Listening:   http://0.0.0.0:{}", server_port);
    println!("  Endpoints:   /sync/status, /sync/changes, /sync/full, /sync/apply");
    if verbose {
        println!("  Logging:     enabled (verbose mode)");
    }
    println!("  Press Ctrl-C to stop");
    println!();

    // Wrap in Arc<Mutex<>> for sync_server
    let db_arc = Arc::new(Mutex::new(db));
    let config_arc = Arc::new(Mutex::new(cfg));

    // Run server with Ctrl-C handler
    runtime.block_on(async {
        // Spawn task to handle Ctrl-C
        tokio::spawn(async {
            if let Ok(()) = tokio::signal::ctrl_c().await {
                println!("\nReceived Ctrl-C, shutting down...");
                sync_server::stop_server();
            }
        });

        // Run the server
        sync_server::start_server(db_arc, config_arc, server_port).await
    }).map_err(voice_error_to_pyerr)?;

    Ok(())
}

/// Stop the sync server.
///
/// Call this from another thread or signal handler to gracefully stop the server.
#[pyfunction]
fn stop_sync_server() -> PyResult<()> {
    sync_server::stop_server();
    Ok(())
}

/// Apply sync changes from a peer to the local database.
///
/// This is the same logic used by the sync server's /sync/apply endpoint.
///
/// Args:
///     db: Database instance
///     changes: List of change dicts, each with keys:
///         - entity_type: "note", "tag", "note_tag", "note_attachment", or "audio_file"
///         - entity_id: UUID hex string
///         - operation: "create", "update", or "delete"
///         - timestamp: RFC3339 timestamp string
///         - device_id: Source device UUID hex string
///         - device_name: Optional source device name
///         - data: Dict with entity-specific data
///     peer_device_id: UUID hex string of the peer device
///     peer_device_name: Optional name of the peer device
///
/// Returns:
///     Dict with keys: applied, conflicts, errors
#[pyfunction]
#[pyo3(signature = (db, changes, peer_device_id, peer_device_name=None))]
fn apply_sync_changes<'py>(
    py: Python<'py>,
    db: &PyDatabase,
    changes: pyo3::Bound<'py, PyList>,
    peer_device_id: &str,
    peer_device_name: Option<&str>,
) -> PyResult<PyObject> {
    let db_ref = db.inner_ref()?;

    // Convert Python dicts or dataclass objects to SyncChange structs
    let mut rust_changes = Vec::new();
    for change_item in changes.iter() {
        // Try dict access first, then attribute access (for dataclasses)
        let (entity_type, entity_id, operation, timestamp, device_id, device_name, data_json) =
            if let Ok(change_dict) = change_item.downcast::<PyDict>() {
                // Dict-style access
                let entity_type: String = change_dict
                    .get_item("entity_type")?
                    .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("missing entity_type"))?
                    .extract()?;
                let entity_id: String = change_dict
                    .get_item("entity_id")?
                    .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("missing entity_id"))?
                    .extract()?;
                let operation: String = change_dict
                    .get_item("operation")?
                    .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("missing operation"))?
                    .extract()?;
                let timestamp: String = change_dict
                    .get_item("timestamp")?
                    .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("missing timestamp"))?
                    .extract()?;
                let device_id: String = change_dict
                    .get_item("device_id")?
                    .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("missing device_id"))?
                    .extract()?;
                let device_name: Option<String> = change_dict
                    .get_item("device_name")?
                    .and_then(|v| v.extract().ok());
                let data_dict = change_dict
                    .get_item("data")?
                    .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("missing data"))?;
                let data_json = pydict_to_json_value(py, &data_dict)?;
                (entity_type, entity_id, operation, timestamp, device_id, device_name, data_json)
            } else {
                // Attribute access (for dataclasses like SyncChange)
                let entity_type: String = change_item.getattr("entity_type")?.extract()?;
                let entity_id: String = change_item.getattr("entity_id")?.extract()?;
                let operation: String = change_item.getattr("operation")?.extract()?;
                let timestamp: String = change_item.getattr("timestamp")?.extract()?;
                let device_id: String = change_item.getattr("device_id")?.extract()?;
                let device_name: Option<String> = change_item
                    .getattr("device_name")
                    .ok()
                    .and_then(|v| v.extract().ok());
                let data_obj = change_item.getattr("data")?;
                let data_json = pydict_to_json_value(py, &data_obj)?;
                (entity_type, entity_id, operation, timestamp, device_id, device_name, data_json)
            };

        rust_changes.push(sync_client::SyncChange {
            entity_type,
            entity_id,
            operation,
            timestamp,
            device_id,
            device_name,
            data: data_json,
        });
    }

    // Apply changes
    let (applied, conflicts, errors) = sync_server::apply_changes_from_peer(
        db_ref,
        &rust_changes,
        peer_device_id,
        peer_device_name,
    )
    .map_err(voice_error_to_pyerr)?;

    // Return result dict
    let result = PyDict::new(py);
    result.set_item("applied", applied)?;
    result.set_item("conflicts", conflicts)?;
    let errors_list = PyList::new(py, &errors)?;
    result.set_item("errors", errors_list)?;
    Ok(result.into_any().unbind())
}

/// Convert a Python object to serde_json::Value
fn pydict_to_json_value(py: Python<'_>, obj: &pyo3::Bound<'_, pyo3::PyAny>) -> PyResult<serde_json::Value> {
    if obj.is_none() {
        return Ok(serde_json::Value::Null);
    }
    if let Ok(b) = obj.extract::<bool>() {
        return Ok(serde_json::Value::Bool(b));
    }
    if let Ok(i) = obj.extract::<i64>() {
        return Ok(serde_json::json!(i));
    }
    if let Ok(f) = obj.extract::<f64>() {
        return Ok(serde_json::json!(f));
    }
    if let Ok(s) = obj.extract::<String>() {
        return Ok(serde_json::Value::String(s));
    }
    if let Ok(list) = obj.downcast::<PyList>() {
        let mut arr = Vec::new();
        for item in list.iter() {
            arr.push(pydict_to_json_value(py, &item)?);
        }
        return Ok(serde_json::Value::Array(arr));
    }
    if let Ok(dict) = obj.downcast::<PyDict>() {
        let mut map = serde_json::Map::new();
        for (key, value) in dict.iter() {
            let key_str: String = key.extract()?;
            map.insert(key_str, pydict_to_json_value(py, &value)?);
        }
        return Ok(serde_json::Value::Object(map));
    }
    // Fallback: try to convert to string
    Ok(serde_json::Value::String(obj.str()?.to_string()))
}

/// Convert a PyObject to serde_json::Value
fn pyobject_to_json_value(py: Python<'_>, obj: &PyObject) -> PyResult<serde_json::Value> {
    pydict_to_json_value(py, obj.bind(py))
}

// ============================================================================
// Merge wrapper
// ============================================================================

#[pyclass(name = "MergeResult")]
pub struct PyMergeResult {
    inner: merge::MergeResult,
}

#[pymethods]
impl PyMergeResult {
    #[getter]
    fn content(&self) -> &str {
        &self.inner.content
    }

    #[getter]
    fn has_conflicts(&self) -> bool {
        self.inner.has_conflicts
    }

    #[getter]
    fn conflict_count(&self) -> usize {
        self.inner.conflict_count
    }
}

#[pyfunction]
#[pyo3(name = "merge_content")]
fn py_merge_content(
    local: &str,
    remote: &str,
    local_label: &str,
    remote_label: &str,
) -> PyMergeResult {
    let result = merge::merge_content(local, remote, local_label, remote_label);
    PyMergeResult { inner: result }
}

// ============================================================================
// Search wrappers
// ============================================================================

#[pyclass(name = "ParsedSearch")]
pub struct PyParsedSearch {
    inner: search::ParsedSearch,
}

#[pymethods]
impl PyParsedSearch {
    #[getter]
    fn tag_terms(&self) -> Vec<String> {
        self.inner.tag_terms.clone()
    }

    #[getter]
    fn free_text(&self) -> &str {
        &self.inner.free_text
    }

    #[getter]
    fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }
}

#[pyfunction]
#[pyo3(name = "parse_search_input")]
fn py_parse_search_input(search_input: &str) -> PyParsedSearch {
    let result = search::parse_search_input(search_input);
    PyParsedSearch { inner: result }
}

#[pyclass(name = "SearchResult")]
pub struct PySearchResult {
    notes: Vec<database::NoteRow>,
    ambiguous_tags: Vec<String>,
    not_found_tags: Vec<String>,
}

#[pymethods]
impl PySearchResult {
    #[getter]
    fn notes<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let list = PyList::empty(py);
        for note in &self.notes {
            list.append(note_row_to_dict(py, note)?)?;
        }
        Ok(list.into_any().unbind())
    }

    #[getter]
    fn ambiguous_tags(&self) -> Vec<String> {
        self.ambiguous_tags.clone()
    }

    #[getter]
    fn not_found_tags(&self) -> Vec<String> {
        self.not_found_tags.clone()
    }
}

#[pyfunction]
#[pyo3(name = "execute_search")]
fn py_execute_search(db: &PyDatabase, search_input: &str) -> PyResult<PySearchResult> {
    let db_ref = db.inner_ref()?;
    let result = search::execute_search(db_ref, search_input).map_err(voice_error_to_pyerr)?;
    Ok(PySearchResult {
        notes: result.notes,
        ambiguous_tags: result.ambiguous_tags,
        not_found_tags: result.not_found_tags,
    })
}

// ============================================================================
// Validation functions
// ============================================================================

#[pyfunction]
#[pyo3(name = "validate_uuid_hex")]
fn py_validate_uuid_hex(value: &str, field_name: &str) -> PyResult<String> {
    let uuid = validation::validate_uuid_hex(value, field_name).map_err(voice_error_to_pyerr)?;
    Ok(validation::uuid_to_hex(&uuid))
}

#[pyfunction]
#[pyo3(name = "uuid_to_hex")]
fn py_uuid_to_hex(value: &str) -> PyResult<String> {
    let uuid = validation::validate_uuid_hex(value, "uuid").map_err(voice_error_to_pyerr)?;
    Ok(validation::uuid_to_hex(&uuid))
}

#[pyfunction]
#[pyo3(name = "validate_note_id")]
fn py_validate_note_id(note_id: &str) -> PyResult<String> {
    let uuid = validation::validate_note_id(note_id).map_err(voice_error_to_pyerr)?;
    Ok(validation::uuid_to_hex(&uuid))
}

#[pyfunction]
#[pyo3(name = "validate_tag_id")]
fn py_validate_tag_id(tag_id: &str) -> PyResult<String> {
    let uuid = validation::validate_tag_id(tag_id).map_err(voice_error_to_pyerr)?;
    Ok(validation::uuid_to_hex(&uuid))
}

#[pyfunction]
#[pyo3(name = "validate_tag_name")]
fn py_validate_tag_name(name: &str) -> PyResult<()> {
    validation::validate_tag_name(name).map_err(voice_error_to_pyerr)
}

#[pyfunction]
#[pyo3(name = "validate_note_content")]
fn py_validate_note_content(content: &str) -> PyResult<()> {
    validation::validate_note_content(content).map_err(voice_error_to_pyerr)
}

#[pyfunction]
#[pyo3(name = "validate_search_query")]
#[pyo3(signature = (query=None))]
fn py_validate_search_query(query: Option<&str>) -> PyResult<()> {
    validation::validate_search_query(query).map_err(voice_error_to_pyerr)
}

#[pyfunction]
#[pyo3(name = "validate_datetime")]
#[pyo3(signature = (value, field_name=None))]
fn py_validate_datetime(value: &str, field_name: Option<&str>) -> PyResult<()> {
    let field = field_name.unwrap_or("datetime");
    validation::validate_datetime(value, field).map_err(voice_error_to_pyerr)
}

#[pyfunction]
#[pyo3(name = "validate_audio_file_id")]
fn py_validate_audio_file_id(audio_file_id: &str) -> PyResult<String> {
    let uuid = validation::validate_audio_file_id(audio_file_id).map_err(voice_error_to_pyerr)?;
    Ok(validation::uuid_to_hex(&uuid))
}

#[pyfunction]
#[pyo3(name = "validate_attachment_id")]
fn py_validate_attachment_id(attachment_id: &str) -> PyResult<String> {
    let uuid = validation::validate_attachment_id(attachment_id).map_err(voice_error_to_pyerr)?;
    Ok(validation::uuid_to_hex(&uuid))
}

#[pyfunction]
#[pyo3(name = "validate_audio_extension")]
fn py_validate_audio_extension(filename: &str) -> PyResult<()> {
    validation::validate_audio_extension(filename).map_err(voice_error_to_pyerr)
}

// ============================================================================
// Database helper
// ============================================================================

#[pyfunction]
#[pyo3(name = "set_local_device_id")]
fn py_set_local_device_id(device_id: &str) -> PyResult<()> {
    let uuid = validation::validate_uuid_hex(device_id, "device_id").map_err(voice_error_to_pyerr)?;
    database::set_local_device_id(uuid);
    Ok(())
}

#[pyfunction]
#[pyo3(name = "get_local_device_id")]
fn py_get_local_device_id() -> PyResult<String> {
    let uuid = database::get_local_device_id();
    Ok(validation::uuid_to_hex(&uuid))
}

// ============================================================================
// Python module
// ============================================================================

#[pymodule]
fn voicecore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Register error types
    m.add("ValidationError", m.py().get_type::<ValidationError>())?;
    m.add("DatabaseError", m.py().get_type::<DatabaseError>())?;
    m.add("SyncError", m.py().get_type::<SyncError>())?;

    // Register database class
    m.add_class::<PyDatabase>()?;

    // Register config class
    m.add_class::<PyConfig>()?;

    // Register sync client classes and functions
    m.add_class::<PySyncResult>()?;
    m.add_class::<PySyncClient>()?;
    m.add_function(wrap_pyfunction!(sync_all_peers, m)?)?;

    // Register sync server functions
    m.add_function(wrap_pyfunction!(start_sync_server, m)?)?;
    m.add_function(wrap_pyfunction!(stop_sync_server, m)?)?;
    m.add_function(wrap_pyfunction!(apply_sync_changes, m)?)?;

    // Register search classes and functions
    m.add_class::<PySearchResult>()?;
    m.add_class::<PyParsedSearch>()?;
    m.add_function(wrap_pyfunction!(py_parse_search_input, m)?)?;
    m.add_function(wrap_pyfunction!(py_execute_search, m)?)?;

    // Register merge classes and functions
    m.add_class::<PyMergeResult>()?;
    m.add_function(wrap_pyfunction!(py_merge_content, m)?)?;

    // Register validation functions
    m.add_function(wrap_pyfunction!(py_validate_uuid_hex, m)?)?;
    m.add_function(wrap_pyfunction!(py_uuid_to_hex, m)?)?;
    m.add_function(wrap_pyfunction!(py_validate_note_id, m)?)?;
    m.add_function(wrap_pyfunction!(py_validate_tag_id, m)?)?;
    m.add_function(wrap_pyfunction!(py_validate_tag_name, m)?)?;
    m.add_function(wrap_pyfunction!(py_validate_note_content, m)?)?;
    m.add_function(wrap_pyfunction!(py_validate_search_query, m)?)?;
    m.add_function(wrap_pyfunction!(py_validate_datetime, m)?)?;
    m.add_function(wrap_pyfunction!(py_validate_audio_file_id, m)?)?;
    m.add_function(wrap_pyfunction!(py_validate_attachment_id, m)?)?;
    m.add_function(wrap_pyfunction!(py_validate_audio_extension, m)?)?;

    // Register database helper functions
    m.add_function(wrap_pyfunction!(py_set_local_device_id, m)?)?;
    m.add_function(wrap_pyfunction!(py_get_local_device_id, m)?)?;

    Ok(())
}
