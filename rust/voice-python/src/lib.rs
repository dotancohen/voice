//! Python bindings for VoiceCore.
//!
//! This crate provides PyO3 bindings to expose the voicecore library to Python.

use pyo3::create_exception;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashMap;

use voicecore_lib::{config, database, error, merge, search, validation};

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

    // Register database helper functions
    m.add_function(wrap_pyfunction!(py_set_local_device_id, m)?)?;
    m.add_function(wrap_pyfunction!(py_get_local_device_id, m)?)?;

    Ok(())
}
