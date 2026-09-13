//! Python bindings for VoiceCore.
//!
//! This crate provides PyO3 bindings to expose the voicecore library to Python.

use pyo3::create_exception;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use voicecore_lib::{config, database, error, file_storage, merge, models, search, sync_client, sync_server, validation};

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
    // The timezone each timestamp was written in: the offset renders the wall
    // clock the author was reading, the name says where that was.
    dict.set_item("created_at_offset", &note.created_at_offset)?;
    dict.set_item("created_at_zone", &note.created_at_zone)?;
    dict.set_item("modified_at_offset", &note.modified_at_offset)?;
    dict.set_item("modified_at_zone", &note.modified_at_zone)?;
    dict.set_item("deleted_at_offset", &note.deleted_at_offset)?;
    dict.set_item("deleted_at_zone", &note.deleted_at_zone)?;
    // Include raw display_cache JSON string (Python will parse it)
    dict.set_item("display_cache", &note.display_cache)?;
    // Include raw list_display_cache JSON string (Python will parse it)
    dict.set_item("list_display_cache", &note.list_display_cache)?;
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
    dict.set_item("duration_seconds", &audio_file.duration_seconds)?;
    dict.set_item("summary", &audio_file.summary)?;
    dict.set_item("device_id", &audio_file.device_id)?;
    dict.set_item("modified_at", &audio_file.modified_at)?;
    dict.set_item("deleted_at", &audio_file.deleted_at)?;
    dict.set_item("storage_provider", &audio_file.storage_provider)?;
    dict.set_item("storage_key", &audio_file.storage_key)?;
    dict.set_item("storage_uploaded_at", &audio_file.storage_uploaded_at)?;
    dict.set_item("imported_at_offset", &audio_file.imported_at_offset)?;
    dict.set_item("imported_at_zone", &audio_file.imported_at_zone)?;
    dict.set_item("file_created_at_offset", &audio_file.file_created_at_offset)?;
    dict.set_item("file_created_at_zone", &audio_file.file_created_at_zone)?;
    dict.set_item("modified_at_offset", &audio_file.modified_at_offset)?;
    dict.set_item("modified_at_zone", &audio_file.modified_at_zone)?;
    dict.set_item("deleted_at_offset", &audio_file.deleted_at_offset)?;
    dict.set_item("deleted_at_zone", &audio_file.deleted_at_zone)?;
    dict.set_item("local_name", &audio_file.local_name)?;
    dict.set_item("content_sha256", &audio_file.content_sha256)?;
    dict.set_item("storage_encrypted", audio_file.storage_encrypted)?;
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
    dict.set_item("created_at_offset", &transcription.created_at_offset)?;
    dict.set_item("created_at_zone", &transcription.created_at_zone)?;
    Ok(dict)
}

fn tag_change_result_to_dict<'py>(py: Python<'py>, result: &database::TagChangeResult) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("changed", result.changed)?;
    dict.set_item("note_id", &result.note_id)?;
    dict.set_item("list_cache_rebuilt", result.list_cache_rebuilt)?;
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

    fn inner_mut(&mut self) -> PyResult<&mut database::Database> {
        self.inner
            .as_mut()
            .ok_or_else(|| DatabaseError::new_err("Database has been closed"))
    }
}

#[pymethods]
impl PyDatabase {
    #[new]
    #[pyo3(signature = (db_path=None, account_id=None))]
    fn new(db_path: Option<&str>, account_id: Option<&str>) -> PyResult<Self> {
        let db = match db_path {
            Some(path) => match account_id {
                Some(account) => database::Database::new_for_account(path, account),
                None => database::Database::new(path),
            },
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

    fn merge_notes(&self, note_id_1: &str, note_id_2: &str) -> PyResult<String> {
        self.inner_ref()?.merge_notes(note_id_1, note_id_2).map_err(voice_error_to_pyerr)
    }

    fn get_all_notes<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let notes = self.inner_ref()?.get_all_notes().map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for note in &notes {
            list.append(note_row_to_dict(py, note)?)?;
        }
        Ok(list.into_any().unbind())
    }

    /// Make one of a note's attachments the one that stands for it.
    #[pyo3(signature = (note_id, attachment_id=None))]
    fn set_primary_attachment(&self, note_id: &str, attachment_id: Option<&str>) -> PyResult<bool> {
        self.inner_ref()?.set_primary_attachment(note_id, attachment_id).map_err(voice_error_to_pyerr)
    }

    /// The attachment that stands for this note, if one was chosen.
    fn get_primary_attachment(&self, note_id: &str) -> PyResult<Option<String>> {
        self.inner_ref()?.get_primary_attachment(note_id).map_err(voice_error_to_pyerr)
    }

    /// Make one of a recording's transcriptions the one that stands for it.
    #[pyo3(signature = (audio_file_id, transcription_id=None))]
    fn set_primary_transcription(&self, audio_file_id: &str, transcription_id: Option<&str>) -> PyResult<bool> {
        self.inner_ref()?.set_primary_transcription(audio_file_id, transcription_id).map_err(voice_error_to_pyerr)
    }

    /// The transcription that stands for this recording, if one was chosen.
    fn get_primary_transcription(&self, audio_file_id: &str) -> PyResult<Option<String>> {
        self.inner_ref()?.get_primary_transcription(audio_file_id).map_err(voice_error_to_pyerr)
    }

    /// The notes in the trash: deleted, still here, newest deletion first.
    fn get_deleted_notes<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let notes = self.inner_ref()?.get_deleted_notes().map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for note in &notes {
            list.append(note_row_to_dict(py, note)?)?;
        }
        Ok(list.into_any().unbind())
    }

    /// Take a note out of the trash. False when it was not in there.
    fn undelete_note(&self, note_id: &str) -> PyResult<bool> {
        self.inner_ref()?.undelete_note(note_id).map_err(voice_error_to_pyerr)
    }

    /// Empty one note out of the trash for good, on every device.
    ///
    /// Returns the ids of the recordings that went with it, so the caller
    /// can delete the files themselves.
    fn purge_note(&self, note_id: &str) -> PyResult<Vec<String>> {
        self.inner_ref()?.purge_note(note_id).map_err(voice_error_to_pyerr)
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

    fn reparent_tag(&self, tag_id: &str, new_parent_id: Option<&str>) -> PyResult<bool> {
        self.inner_ref()?.reparent_tag(tag_id, new_parent_id).map_err(voice_error_to_pyerr)
    }

    fn delete_tag(&self, tag_id: &str) -> PyResult<bool> {
        self.inner_ref()?.delete_tag(tag_id).map_err(voice_error_to_pyerr)
    }

    fn add_tag_to_note<'py>(&self, py: Python<'py>, note_id: &str, tag_id: &str) -> PyResult<PyObject> {
        let result = self.inner_ref()?
            .add_tag_to_note(note_id, tag_id)
            .map_err(voice_error_to_pyerr)?;
        Ok(tag_change_result_to_dict(py, &result)?.into_any().unbind())
    }

    fn remove_tag_from_note<'py>(&self, py: Python<'py>, note_id: &str, tag_id: &str) -> PyResult<PyObject> {
        let result = self.inner_ref()?
            .remove_tag_from_note(note_id, tag_id)
            .map_err(voice_error_to_pyerr)?;
        Ok(tag_change_result_to_dict(py, &result)?.into_any().unbind())
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

    fn get_peer_last_sync(&self, peer_device_id: &str) -> PyResult<Option<i64>> {
        self.inner_ref()?
            .get_peer_last_sync(peer_device_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Reset sync timestamps to NULL to force re-fetching all data from peers.
    /// Unlike clearing sync peers, this preserves peer configuration.
    fn reset_sync_timestamps(&self) -> PyResult<()> {
        self.inner_ref()?
            .reset_sync_timestamps()
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
        since: Option<i64>,
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

    /// Write-order feed: changes with seq > cursor (and <= upto when given).
    /// Returns {"changes": [...], "next_cursor": int, "is_complete": bool}.
    #[pyo3(signature = (cursor=0, upto=None, limit=1000))]
    fn get_changes_after_seq<'py>(&self, py: Python<'py>, cursor: i64, upto: Option<i64>, limit: i64) -> PyResult<PyObject> {
        let feed = self
            .inner_ref()?
            .get_changes_after_seq(cursor, upto, limit)
            .map_err(voice_error_to_pyerr)?;
        let result = PyDict::new(py);
        let changes_list = PyList::empty(py);
        for change in &feed.changes {
            changes_list.append(hashmap_to_pydict(py, change)?)?;
        }
        result.set_item("changes", changes_list)?;
        result.set_item("next_cursor", feed.next_cursor)?;
        result.set_item("is_complete", feed.is_complete)?;
        result.set_item("latest_timestamp", feed.latest_timestamp)?;
        Ok(result.into_any().unbind())
    }

    /// The largest seq written so far (end of this database's feed).
    fn current_seq(&self) -> PyResult<i64> {
        self.inner_ref()?.current_seq().map_err(voice_error_to_pyerr)
    }

    /// Identity of this database (changes when the database is replaced).
    fn database_id(&self) -> PyResult<String> {
        self.inner_ref()?.database_id().map_err(voice_error_to_pyerr)
    }

    /// The account this database belongs to (ACCT-1).
    fn account_id(&self) -> PyResult<String> {
        self.inner_ref()?.account_id().map_err(voice_error_to_pyerr)
    }

    /// Move this database, notes and all, to another account (ACCT-5): a
    /// snapshot first, then the id is rewritten and every peer forgotten.
    fn move_to_account(&self, account_id: &str) -> PyResult<()> {
        self.inner_ref()?.move_to_account(account_id).map_err(voice_error_to_pyerr)
    }

    /// What is on this device only (Stage 10): notes and recordings, as a dict.
    #[pyo3(signature = (audio_dir=None))]
    fn not_duplicated<'py>(&self, py: Python<'py>, audio_dir: Option<&str>) -> PyResult<PyObject> {
        let counts = self.inner_ref()?.not_duplicated(audio_dir.map(std::path::Path::new)).map_err(voice_error_to_pyerr)?;
        let d = PyDict::new(py);
        d.set_item("notes", counts.notes)?;
        d.set_item("recordings", counts.recordings)?;
        Ok(d.into_any().unbind())
    }

    /// The peers known to hold a copy of a recording, as dicts with peer_id and at.
    fn copies_of<'py>(&self, py: Python<'py>, audio_id: &str) -> PyResult<PyObject> {
        let copies = self.inner_ref()?.copies_of(audio_id).map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for c in copies {
            let d = PyDict::new(py);
            d.set_item("peer_id", c.peer_id)?;
            d.set_item("at", c.at)?;
            list.append(d)?;
        }
        Ok(list.into_any().unbind())
    }

    /// Every peer dealt with: peer_id, peer_name, last_reached_at, last_operation.
    fn peer_summaries<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let peers = self.inner_ref()?.peer_summaries().map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for p in peers {
            let d = PyDict::new(py);
            d.set_item("peer_id", p.peer_id)?;
            d.set_item("peer_name", p.peer_name)?;
            d.set_item("last_reached_at", p.last_reached_at)?;
            d.set_item("last_operation", p.last_operation)?;
            list.append(d)?;
        }
        Ok(list.into_any().unbind())
    }

    /// Every device of the account, as its card says (CARD-1).
    fn list_devices<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let cards = self.inner_ref()?.list_device_cards().map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for c in cards {
            let d = PyDict::new(py);
            d.set_item("device_id", c.device_id)?;
            d.set_item("name", c.name)?;
            d.set_item("certificate_fingerprint", c.certificate_fingerprint)?;
            d.set_item("addresses", c.addresses)?;
            d.set_item("listens", c.listens == "1")?;
            d.set_item("revoked", c.revoked == "1")?;
            d.set_item("application", c.application)?;
            list.append(d)?;
        }
        Ok(list.into_any().unbind())
    }

    /// Let a device into the account: write its card with the hash of its
    /// key. Pairing does this; tests do it directly.
    #[pyo3(signature = (device_id, name, key_hash, certificate_fingerprint="", application="voice"))]
    fn admit_device(&self, device_id: &str, name: &str, key_hash: &str, certificate_fingerprint: &str, application: &str) -> PyResult<()> {
        let card = voicecore_lib::versions::DeviceCard {
            device_id: device_id.to_string(),
            name: name.to_string(),
            certificate_fingerprint: certificate_fingerprint.to_string(),
            addresses: String::new(),
            listens: "0".to_string(),
            key_hash: key_hash.to_string(),
            revoked: "0".to_string(),
            application: application.to_string(),
        };
        self.inner_ref()?.admit_device_card(&card).map_err(voice_error_to_pyerr)
    }

    /// Revoke a device of the account (AUTH-6): one way, and it travels.
    fn revoke_device(&self, device_id: &str) -> PyResult<()> {
        self.inner_ref()?.revoke_device(device_id).map_err(voice_error_to_pyerr)
    }

    /// Copy the database into its snapshot directory; returns the path.
    fn snapshot(&self) -> PyResult<String> {
        let path = self.inner_ref()?.snapshot().map_err(voice_error_to_pyerr)?;
        Ok(path.to_string_lossy().to_string())
    }

    /// Every snapshot beside this database, newest first, as dicts with
    /// name, path, size_bytes and note_count.
    fn list_snapshots<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let snapshots = self.inner_ref()?.list_snapshots().map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for s in snapshots {
            let d = PyDict::new(py);
            d.set_item("name", s.name)?;
            d.set_item("path", s.path)?;
            d.set_item("size_bytes", s.size_bytes)?;
            d.set_item("note_count", s.note_count)?;
            list.append(d)?;
        }
        Ok(list.into_any().unbind())
    }

    /// Replace the database's contents with a snapshot's (SNAP-4); the
    /// state replaced is snapshotted first.
    fn restore_snapshot(&mut self, name: &str) -> PyResult<()> {
        self.inner_mut()?.restore_snapshot(name).map_err(voice_error_to_pyerr)
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

    #[pyo3(signature = (note_id, created_at, content, modified_at=None, deleted_at=None, sync_received_at=None, primary_attachment_id=None))]
    fn apply_sync_note(
        &self,
        note_id: &str,
        created_at: i64,
        content: &str,
        modified_at: Option<i64>,
        deleted_at: Option<i64>,
        sync_received_at: Option<i64>,
        primary_attachment_id: Option<&str>,
    ) -> PyResult<bool> {
        self.inner_ref()?
            .apply_sync_note(
                note_id,
                created_at,
                content,
                modified_at,
                deleted_at,
                sync_received_at,
                primary_attachment_id,
            )
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (tag_id, name, parent_id, created_at, modified_at=None, deleted_at=None, sync_received_at=None))]
    fn apply_sync_tag(
        &self,
        tag_id: &str,
        name: &str,
        parent_id: Option<&str>,
        created_at: i64,
        modified_at: Option<i64>,
        deleted_at: Option<i64>,
        sync_received_at: Option<i64>,
    ) -> PyResult<bool> {
        self.inner_ref()?
            .apply_sync_tag_with_deleted(tag_id, name, parent_id, created_at, modified_at, deleted_at, sync_received_at)
            .map_err(voice_error_to_pyerr)
    }

    #[pyo3(signature = (note_id, tag_id, created_at, modified_at=None, deleted_at=None, sync_received_at=None))]
    fn apply_sync_note_tag(
        &self,
        note_id: &str,
        tag_id: &str,
        created_at: i64,
        modified_at: Option<i64>,
        deleted_at: Option<i64>,
        sync_received_at: Option<i64>,
    ) -> PyResult<bool> {
        self.inner_ref()?
            .apply_sync_note_tag(note_id, tag_id, created_at, modified_at, deleted_at, sync_received_at)
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
    // Versioned fields and conflicts (see voicecore versions.rs)
    // ========================================================================

    /// Unresolved conflict counts keyed by kind ("content", "delete", "tag", ...)
    /// plus "total".
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

    /// All conflicts (unresolved only unless include_resolved), newest first.
    #[pyo3(signature = (include_resolved=false))]
    fn get_conflicts<'py>(&self, py: Python<'py>, include_resolved: bool) -> PyResult<PyObject> {
        let conflicts = self
            .inner_ref()?
            .get_conflicts(include_resolved)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for c in &conflicts {
            list.append(json_value_to_pyobject(py, &c.to_json())?)?;
        }
        Ok(list.into_any().unbind())
    }

    /// Unresolved conflicts for one entity (e.g. "note", note_id).
    fn get_entity_conflicts<'py>(&self, py: Python<'py>, entity_type: &str, entity_id: &str) -> PyResult<PyObject> {
        let conflicts = self
            .inner_ref()?
            .get_entity_conflicts(entity_type, entity_id)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for c in &conflicts {
            list.append(json_value_to_pyobject(py, &c.to_json())?)?;
        }
        Ok(list.into_any().unbind())
    }

    /// One conflict by id or unique id prefix; None when there is no match,
    /// an error when the prefix is ambiguous.
    fn get_conflict<'py>(&self, py: Python<'py>, id_or_prefix: &str) -> PyResult<Option<PyObject>> {
        let c = self
            .inner_ref()?
            .get_conflict(id_or_prefix)
            .map_err(voice_error_to_pyerr)?;
        match c {
            Some(c) => Ok(Some(json_value_to_pyobject(py, &c.to_json())?)),
            None => Ok(None),
        }
    }

    /// Every unresolved conflict that concerns a note (its fields, tag links,
    /// attachments and their transcriptions).
    fn get_note_conflicts<'py>(&self, py: Python<'py>, note_id: &str) -> PyResult<PyObject> {
        let conflicts = self
            .inner_ref()?
            .get_note_conflicts(note_id)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for c in &conflicts {
            list.append(json_value_to_pyobject(py, &c.to_json())?)?;
        }
        Ok(list.into_any().unbind())
    }

    /// Conflict kinds ("content", "delete", "tag", "attachment", "transcription", ...)
    /// that are unresolved for a note or anything attached to it.
    fn get_note_conflict_types(&self, note_id: &str) -> PyResult<Vec<String>> {
        self.inner_ref()?
            .get_note_conflict_types(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Accept the merged value as it stands (markers included, if any).
    fn accept_conflict(&self, conflict_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .accept_conflict(conflict_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Resolve a conflict by writing a new value for the field.
    fn resolve_conflict_with_content(&self, conflict_id: &str, content: &str) -> PyResult<bool> {
        self.inner_ref()?
            .resolve_conflict_with_content(conflict_id, content)
            .map_err(voice_error_to_pyerr)
    }

    /// Every version of one field, oldest first.
    fn get_field_history<'py>(&self, py: Python<'py>, entity_type: &str, entity_id: &str, field: &str) -> PyResult<PyObject> {
        let versions = self
            .inner_ref()?
            .get_field_history(entity_type, entity_id, field)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for v in &versions {
            list.append(json_value_to_pyobject(py, &v.to_json())?)?;
        }
        Ok(list.into_any().unbind())
    }

    /// One version by hex id.
    fn get_version<'py>(&self, py: Python<'py>, version_id: &str) -> PyResult<Option<PyObject>> {
        let bytes = voicecore_lib::versions::hex_to_bytes(version_id).map_err(voice_error_to_pyerr)?;
        let v = self.inner_ref()?.get_version(&bytes).map_err(voice_error_to_pyerr)?;
        match v {
            Some(v) => Ok(Some(json_value_to_pyobject(py, &v.to_json())?)),
            None => Ok(None),
        }
    }

    // ========================================================================
    // Synced settings (versioned key/value store shared by every device)
    // ========================================================================

    fn get_setting(&self, key: &str) -> PyResult<Option<String>> {
        self.inner_ref()?.get_setting(key).map_err(voice_error_to_pyerr)
    }

    fn set_setting(&self, key: &str, value: &str) -> PyResult<()> {
        self.inner_ref()?.set_setting(key, value).map_err(voice_error_to_pyerr)
    }

    fn get_all_settings<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let settings = self.inner_ref()?.get_all_settings().map_err(voice_error_to_pyerr)?;
        let dict = PyDict::new(py);
        for (k, v) in &settings {
            dict.set_item(k, v)?;
        }
        Ok(dict.into_any().unbind())
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

    #[pyo3(signature = (id, note_id, attachment_id, attachment_type, created_at, modified_at=None, deleted_at=None, sync_received_at=None))]
    fn apply_sync_note_attachment(
        &self,
        id: &str,
        note_id: &str,
        attachment_id: &str,
        attachment_type: &str,
        created_at: i64,
        modified_at: Option<i64>,
        deleted_at: Option<i64>,
        sync_received_at: Option<i64>,
    ) -> PyResult<()> {
        self.inner_ref()?
            .apply_sync_note_attachment(id, note_id, attachment_id, attachment_type, created_at, modified_at, deleted_at, sync_received_at)
            .map_err(voice_error_to_pyerr)
    }

    // ========================================================================
    // AudioFile methods
    // ========================================================================

    #[pyo3(signature = (filename, file_created_at=None))]
    fn create_audio_file(&self, filename: &str, file_created_at: Option<i64>) -> PyResult<String> {
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

    /// Create audio file with duration
    #[pyo3(signature = (filename, file_created_at=None, duration_seconds=None))]
    fn create_audio_file_with_duration(
        &self,
        filename: &str,
        file_created_at: Option<i64>,
        duration_seconds: Option<i64>,
    ) -> PyResult<String> {
        self.inner_ref()?
            .create_audio_file_with_duration(filename, file_created_at, duration_seconds)
            .map_err(voice_error_to_pyerr)
    }

    /// Update audio file duration
    fn update_audio_file_duration(&self, audio_file_id: &str, duration_seconds: i64) -> PyResult<bool> {
        self.inner_ref()?
            .update_audio_file_duration(audio_file_id, duration_seconds)
            .map_err(voice_error_to_pyerr)
    }

    fn update_audio_file_created_at(&self, audio_file_id: &str, file_created_at: i64) -> PyResult<bool> {
        self.inner_ref()?
            .update_audio_file_created_at(audio_file_id, file_created_at)
            .map_err(voice_error_to_pyerr)
    }

    /// Get audio files missing duration
    fn get_audio_files_missing_duration<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let audio_files = self.inner_ref()?
            .get_audio_files_missing_duration()
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for audio_file in &audio_files {
            list.append(audio_file_row_to_dict(py, audio_file)?)?;
        }
        Ok(list.into_any().unbind())
    }

    // ========================================================================
    // Cloud Storage methods
    // ========================================================================

    /// Get audio files that need to be uploaded to cloud storage.
    ///
    /// Returns files where storage_provider is NULL (not yet uploaded).
    fn get_audio_files_pending_upload<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let audio_files = self.inner_ref()?
            .get_audio_files_pending_upload()
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for audio_file in &audio_files {
            list.append(audio_file_row_to_dict(py, audio_file)?)?;
        }
        Ok(list.into_any().unbind())
    }

    /// Update an audio file's cloud storage information after successful upload.
    fn update_audio_file_storage(
        &self,
        audio_file_id: &str,
        storage_provider: &str,
        storage_key: &str,
    ) -> PyResult<bool> {
        self.inner_ref()?
            .update_audio_file_storage(audio_file_id, storage_provider, storage_key)
            .map_err(voice_error_to_pyerr)
    }

    /// Clear an audio file's cloud storage information.
    fn clear_audio_file_storage(&self, audio_file_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .clear_audio_file_storage(audio_file_id)
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

    #[pyo3(signature = (id, imported_at, filename, file_created_at=None, duration_seconds=None, summary=None, modified_at=None, deleted_at=None, sync_received_at=None, storage_provider=None, storage_key=None, storage_uploaded_at=None, primary_transcription_id=None, file_created_at_offset=None, content_sha256=None, storage_encrypted=None))]
    fn apply_sync_audio_file(
        &self,
        id: &str,
        imported_at: i64,
        filename: &str,
        file_created_at: Option<i64>,
        duration_seconds: Option<i64>,
        summary: Option<&str>,
        modified_at: Option<i64>,
        deleted_at: Option<i64>,
        sync_received_at: Option<i64>,
        storage_provider: Option<&str>,
        storage_key: Option<&str>,
        storage_uploaded_at: Option<i64>,
        primary_transcription_id: Option<&str>,
        file_created_at_offset: Option<i32>,
        content_sha256: Option<&str>,
        storage_encrypted: Option<bool>,
    ) -> PyResult<()> {
        self.inner_ref()?
            .apply_sync_audio_file(
                id,
                imported_at,
                filename,
                file_created_at,
                duration_seconds,
                summary,
                modified_at,
                deleted_at,
                sync_received_at,
                storage_provider,
                storage_key,
                storage_uploaded_at,
                primary_transcription_id,
                file_created_at_offset,
                content_sha256,
                storage_encrypted,
            )
            .map_err(voice_error_to_pyerr)
    }

    /// Compute and store a recording's content hash (Stage 13) from its file
    /// under the audio directory, after it is copied there. Returns the hash.
    fn store_content_hash(&self, audio_id: &str, audio_dir: &str) -> PyResult<String> {
        self.inner_ref()?.store_content_hash(audio_id, std::path::Path::new(audio_dir)).map_err(voice_error_to_pyerr)
    }

    // ========================================================================
    // File Storage Configuration
    // ========================================================================

    /// Get the file storage configuration from the database.
    /// Returns None if no configuration has been set yet.
    fn get_file_storage_config<'py>(&self, py: Python<'py>) -> PyResult<Option<PyObject>> {
        let config = self.inner_ref()?
            .get_file_storage_config()
            .map_err(voice_error_to_pyerr)?;
        match config {
            Some(c) => Ok(Some(json_value_to_pyobject(py, &c)?)),
            None => Ok(None),
        }
    }

    /// Set the file storage configuration in the database.
    #[pyo3(signature = (provider, config=None))]
    fn set_file_storage_config(&self, provider: &str, config: Option<&str>) -> PyResult<()> {
        let config_value: Option<serde_json::Value> = config
            .map(|c| serde_json::from_str(c))
            .transpose()
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid JSON: {}", e)))?;
        self.inner_ref()?
            .set_file_storage_config(provider, config_value.as_ref())
            .map_err(voice_error_to_pyerr)
    }

    /// Get file storage configuration as a provider/config pair.
    fn get_file_storage_provider(&self) -> PyResult<String> {
        let config = self.inner_ref()?
            .get_file_storage_config_struct()
            .map_err(voice_error_to_pyerr)?;
        Ok(config.provider)
    }

    /// Check if file storage is enabled (provider is not "none").
    fn is_file_storage_enabled(&self) -> PyResult<bool> {
        let config = self.inner_ref()?
            .get_file_storage_config_struct()
            .map_err(voice_error_to_pyerr)?;
        Ok(config.is_enabled())
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

    /// The most recent transcriptions, newest first.
    ///
    /// What the transcription queue shows once the work is done. `service`
    /// narrows it to one transcription service; None returns every service.
    #[pyo3(signature = (service=None, limit=50))]
    fn get_recent_transcriptions<'py>(
        &self,
        py: Python<'py>,
        service: Option<&str>,
        limit: u32,
    ) -> PyResult<PyObject> {
        let transcriptions = self.inner_ref()?
            .get_recent_transcriptions(service, limit)
            .map_err(voice_error_to_pyerr)?;
        let list = PyList::empty(py);
        for transcription in &transcriptions {
            list.append(transcription_row_to_dict(py, transcription)?)?;
        }
        Ok(list.into_any().unbind())
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

    // ========================================================================
    // Note Display Cache methods
    // ========================================================================

    /// Rebuild the display cache for a single note.
    ///
    /// The cache stores pre-computed data needed for the Note pane display:
    /// tags (with full paths), conflicts, and attachments with audio files and transcriptions.
    fn rebuild_note_cache(&self, note_id: &str) -> PyResult<()> {
        self.inner_ref()?
            .rebuild_note_cache(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Rebuild the display cache for all notes.
    ///
    /// Returns the number of notes processed.
    fn rebuild_all_note_caches(&self) -> PyResult<u32> {
        self.inner_ref()?
            .rebuild_all_note_caches()
            .map_err(voice_error_to_pyerr)
    }

    /// Rebuild the list pane display cache for a single note.
    ///
    /// The cache stores pre-computed data for the notes list pane:
    /// date, marked status, and content preview (first 100 chars).
    fn rebuild_note_list_cache(&self, note_id: &str) -> PyResult<()> {
        self.inner_ref()?
            .rebuild_note_list_cache(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Rebuild the list pane display cache for all notes.
    ///
    /// Returns the number of notes processed.
    fn rebuild_all_note_list_caches(&self) -> PyResult<u32> {
        self.inner_ref()?
            .rebuild_all_note_list_caches()
            .map_err(voice_error_to_pyerr)
    }

    /// Rebuild ALL cache fields for a single note.
    ///
    /// This rebuilds every cache column (note pane display, list pane display)
    /// for the given note.
    fn rebuild_all_caches_for_note(&self, note_id: &str) -> PyResult<()> {
        self.inner_ref()?
            .rebuild_all_caches_for_note(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Rebuild ALL cache fields for all notes in the database.
    ///
    /// Returns a tuple: (notes_processed, cache_fields_per_note, error_list)
    fn rebuild_all_database_caches(&self) -> PyResult<(u32, u32, Vec<String>)> {
        let summary = self.inner_ref()?
            .rebuild_all_database_caches()
            .map_err(voice_error_to_pyerr)?;
        Ok((summary.notes_processed, summary.cache_fields_rebuilt, summary.errors))
    }

    /// Get information about all registered cache fields.
    ///
    /// Returns a list of (table, column, description) tuples.
    fn get_cache_registry_info(&self) -> PyResult<Vec<(String, String, String)>> {
        Ok(database::Database::get_cache_registry_info()
            .iter()
            .map(|info| (info.table.to_string(), info.column.to_string(), info.description.to_string()))
            .collect())
    }

    /// Get full transcription content by ID.
    ///
    /// Used for lazy-loading full content when displaying transcription.
    fn get_transcription_content(&self, transcription_id: &str) -> PyResult<Option<String>> {
        self.inner_ref()?
            .get_transcription_content(transcription_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Update the waveform data in a note's display cache.
    ///
    /// The waveform is an array of amplitude values (0-255) for visualization.
    /// This is called from Python after extracting the waveform with ffmpeg.
    fn update_cache_waveform(&self, note_id: &str, audio_id: &str, waveform: Vec<u8>) -> PyResult<bool> {
        self.inner_ref()?
            .update_cache_waveform(note_id, audio_id, waveform)
            .map_err(voice_error_to_pyerr)
    }

    // ========================================================================
    // Note marking (star/bookmark) methods
    // ========================================================================

    /// Check if a note is marked (starred/bookmarked).
    fn is_note_marked(&self, note_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .is_note_marked(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Mark a note (add the _system/_marked tag).
    /// Returns true if the note was marked, false if already marked.
    fn mark_note(&self, note_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .mark_note(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Unmark a note (remove the _system/_marked tag).
    /// Returns true if the note was unmarked, false if not marked.
    fn unmark_note(&self, note_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .unmark_note(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Toggle a note's marked state.
    /// Returns the new marked state (true if now marked, false if now unmarked).
    fn toggle_note_marked(&self, note_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .toggle_note_marked(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Get the _system tag ID as a hex string for filtering in UI.
    fn get_system_tag_id_hex(&self) -> PyResult<String> {
        self.inner_ref()?
            .get_system_tag_id_hex()
            .map_err(voice_error_to_pyerr)
    }

    // ========================================================================
    // Non-synced file tagging methods
    // ========================================================================

    /// Check if a note is tagged as too-big to sync.
    fn is_note_too_big_to_sync(&self, note_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .is_note_too_big_to_sync(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Tag a note as too-big to sync (add the _system/_nonsynced/_too-big tag).
    /// Returns true if the tag was added, false if already tagged.
    fn tag_note_too_big(&self, note_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .tag_note_too_big(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Remove the too-big tag from a note.
    /// Returns true if the tag was removed, false if not tagged.
    fn untag_note_too_big(&self, note_id: &str) -> PyResult<bool> {
        self.inner_ref()?
            .untag_note_too_big(note_id)
            .map_err(voice_error_to_pyerr)
    }

    /// Get the _too-big tag ID as a hex string.
    fn get_too_big_tag_id_hex(&self) -> PyResult<String> {
        self.inner_ref()?
            .get_too_big_tag_id_hex()
            .map_err(voice_error_to_pyerr)
    }

    /// Get all note IDs that have an audio file attached.
    fn get_notes_for_audio_file(&self, audio_file_id: &str) -> PyResult<Vec<String>> {
        self.inner_ref()?
            .get_notes_for_audio_file(audio_file_id)
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
    /// `config_dir` is the account's directory. With `root`, the machine's
    /// settings come from the root's config.json (Stage 2); without it, the
    /// directory is the whole installation.
    #[pyo3(signature = (config_dir=None, root=None))]
    fn new(config_dir: Option<&str>, root: Option<&str>) -> PyResult<Self> {
        let path = config_dir.map(std::path::PathBuf::from);
        let cfg = match (root, &path) {
            (Some(root), Some(dir)) if std::path::Path::new(root) != dir.as_path() => {
                config::Config::open_account(std::path::Path::new(root), dir).map_err(voice_error_to_pyerr)?
            }
            _ => config::Config::new(path).map_err(voice_error_to_pyerr)?,
        };
        Ok(Self {
            inner: std::sync::Mutex::new(cfg),
        })
    }

    fn get_config_dir(&self) -> PyResult<String> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.config_dir().to_string_lossy().to_string())
    }

    /// The root that holds the machine's settings and certificates.
    fn get_root(&self) -> PyResult<String> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.root().to_string_lossy().to_string())
    }

    /// The periodic backup settings: interval_hours, directory, keep.
    fn get_backup<'py>(&self, py: Python<'py>) -> PyResult<PyObject> {
        let cfg = self.inner.lock().unwrap();
        let d = PyDict::new(py);
        d.set_item("interval_hours", cfg.backup().interval_hours)?;
        d.set_item("directory", cfg.backup().directory.clone())?;
        d.set_item("keep", cfg.backup().keep)?;
        Ok(d.into_any().unbind())
    }

    #[pyo3(signature = (interval_hours, keep, directory=""))]
    fn set_backup(&self, interval_hours: u32, keep: u32, directory: &str) -> PyResult<()> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.set_backup(config::BackupConfig { interval_hours, directory: directory.to_string(), keep }).map_err(voice_error_to_pyerr)
    }

    fn get_public_url(&self) -> PyResult<String> {
        Ok(self.inner.lock().unwrap().public_url().to_string())
    }

    fn set_public_url(&self, url: &str) -> PyResult<()> {
        self.inner.lock().unwrap().set_public_url(url).map_err(voice_error_to_pyerr)
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

    /// Get the maximum sync file size in MB
    fn get_max_sync_file_size_mb(&self) -> PyResult<u32> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.max_sync_file_size_mb())
    }

    /// Set the maximum sync file size in MB
    fn set_max_sync_file_size_mb(&self, size_mb: u32) -> PyResult<()> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.set_max_sync_file_size_mb(size_mb).map_err(voice_error_to_pyerr)
    }

    /// Whether this installation downloads every cloud audio file on sync
    fn get_mirror_audio_files(&self) -> PyResult<bool> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.mirror_audio_files())
    }

    /// Enable or disable mirroring of all cloud audio files on sync
    fn set_mirror_audio_files(&self, enabled: bool) -> PyResult<()> {
        let mut cfg = self.inner.lock().unwrap();
        cfg.set_mirror_audio_files(enabled).map_err(voice_error_to_pyerr)
    }

    /// This device's key for the account, or empty before one was made.
    fn get_device_key(&self) -> PyResult<String> {
        let cfg = self.inner.lock().unwrap();
        Ok(cfg.device_key().to_string())
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

    /// Forget a peer (Stage 5): it leaves the list and its card does not bring it back.
    fn forget_peer(&self, peer_id: &str) -> PyResult<bool> {
        self.inner.lock().unwrap().forget_peer(peer_id).map_err(voice_error_to_pyerr)
    }

    /// A local name for a peer, shown in place of its card's.
    fn rename_peer(&self, peer_id: &str, name: &str) -> PyResult<bool> {
        self.inner.lock().unwrap().rename_peer(peer_id, name).map_err(voice_error_to_pyerr)
    }

    /// Hours of silence after which the listener stops itself; 0 means never.
    fn listener_idle_stop_hours(&self) -> u32 {
        self.inner.lock().unwrap().listener_idle_stop_hours()
    }

    fn set_listener_idle_stop_hours(&self, hours: u32) -> PyResult<()> {
        self.inner.lock().unwrap().set_listener_idle_stop_hours(hours).map_err(voice_error_to_pyerr)
    }

    /// The peer of the last operation, or an empty string.
    fn last_peer_id(&self) -> String {
        self.inner.lock().unwrap().last_peer().map(|p| p.peer_id.clone()).unwrap_or_default()
    }

    fn set_last_peer(&self, peer_id: &str) -> PyResult<()> {
        self.inner.lock().unwrap().set_last_peer(peer_id).map_err(voice_error_to_pyerr)
    }

    fn is_forgotten(&self, peer_id: &str) -> bool {
        self.inner.lock().unwrap().is_forgotten(peer_id)
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
    /// Recordings sent to the peer (deliver, exchange, send)
    #[pyo3(get)]
    sent: i64,
    /// Recordings fetched from the peer (exchange, fetch)
    #[pyo3(get)]
    fetched: i64,
    /// Bytes of recordings moved either way
    #[pyo3(get)]
    bytes_moved: u64,
    #[pyo3(get)]
    errors: Vec<String>,
    /// Non-fatal problems (e.g. cloud uploads that will be retried next sync)
    #[pyo3(get)]
    warnings: Vec<String>,
    /// The id of the operation, on every request of it and in both logs
    #[pyo3(get)]
    request_id: String,
    /// The peer's clock minus this device's, in seconds, past a minute; else 0
    #[pyo3(get)]
    clock_skew_seconds: i64,
}

impl From<sync_client::SyncResult> for PySyncResult {
    fn from(result: sync_client::SyncResult) -> Self {
        Self {
            success: result.success,
            pulled: result.pulled,
            pushed: result.pushed,
            conflicts: result.conflicts,
            sent: result.sent,
            fetched: result.fetched,
            bytes_moved: result.bytes_moved,
            errors: result.errors,
            warnings: result.warnings,
            request_id: result.request_id,
            clock_skew_seconds: result.clock_skew_seconds,
        }
    }
}

/// Sync client for synchronizing with peers
#[pyclass(name = "SyncClient", unsendable)]
pub struct PySyncClient {
    inner: sync_client::SyncClient,
    runtime: tokio::runtime::Runtime,
}

/// Progress handed to a Python callable (stage, done, total, bytes, sentence),
/// taking the interpreter lock for the call only.
struct PyProgressSink(Py<PyAny>);

impl sync_client::ProgressSink for PyProgressSink {
    fn report(&self, progress: sync_client::Progress) {
        Python::with_gil(|py| {
            if let Err(e) = self.0.call1(py, (progress.stage, progress.done, progress.total, progress.bytes, progress.sentence)) {
                e.print(py);
            }
        });
    }
}

impl PySyncClient {
    /// Run a future of the client without holding the interpreter lock: the
    /// interface stays alive while a sync runs, and a server in the same
    /// process (a test's) can answer.
    fn run<T: Send, F: std::future::Future<Output = T> + Send>(&self, py: Python<'_>, future: F) -> T {
        py.allow_threads(|| self.runtime.block_on(future))
    }
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

    /// Join an account from a setup text (PAIR-4). Returns a dict with
    /// account_id, peer_id, peer_name and peer_url.
    fn join<'py>(&self, py: Python<'py>, setup_text: &str) -> PyResult<PyObject> {
        let joined = self.run(py, self.inner.join(setup_text)).map_err(voice_error_to_pyerr)?;
        let dict = PyDict::new(py);
        dict.set_item("account_id", joined.account_id)?;
        dict.set_item("peer_id", joined.peer_id)?;
        dict.set_item("peer_name", joined.peer_name)?;
        dict.set_item("peer_url", joined.peer_url)?;
        Ok(dict.into_any().unbind())
    }

    /// Move this device to another account by its code (Stage 1): a dict
    /// with account_id, peer_id, peer_name, peer_url and tags_merged.
    fn move_to<'py>(&self, py: Python<'py>, setup_text: &str) -> PyResult<PyObject> {
        let (joined, merged) = self.run(py, self.inner.move_to(setup_text)).map_err(voice_error_to_pyerr)?;
        let dict = PyDict::new(py);
        dict.set_item("account_id", joined.account_id)?;
        dict.set_item("peer_id", joined.peer_id)?;
        dict.set_item("peer_name", joined.peer_name)?;
        dict.set_item("peer_url", joined.peer_url)?;
        dict.set_item("tags_merged", merged)?;
        Ok(dict.into_any().unbind())
    }

    /// Give a server this device's account by its grant text (PAIR-5).
    fn grant_host<'py>(&self, py: Python<'py>, setup_text: &str, label: &str) -> PyResult<PyObject> {
        let joined = self.run(py, self.inner.grant_host(setup_text, label)).map_err(voice_error_to_pyerr)?;
        let dict = PyDict::new(py);
        dict.set_item("account_id", joined.account_id)?;
        dict.set_item("peer_id", joined.peer_id)?;
        dict.set_item("peer_name", joined.peer_name)?;
        dict.set_item("peer_url", joined.peer_url)?;
        Ok(dict.into_any().unbind())
    }

    /// Where progress goes (Stage 4): a callable of (stage, done, total, bytes, sentence), or None.
    #[pyo3(signature = (callback=None))]
    fn set_progress(&self, callback: Option<Py<PyAny>>) {
        self.inner.set_progress_sink(callback.map(|c| Arc::new(PyProgressSink(c)) as Arc<dyn sync_client::ProgressSink>));
    }

    /// Cancel the operation under way, from another thread: it stops at its
    /// next page, file or chunk, and a transfer under way stays resumable.
    fn cancel(&self) {
        self.inner.cancel();
    }

    /// Check the connection to a peer (Stage 12): one row per thing that
    /// can be wrong, as dicts with name, passed, detail and code.
    fn check<'py>(&self, py: Python<'py>, peer_id: &str) -> PyResult<PyObject> {
        let rows = self.run(py, self.inner.check(peer_id));
        let list = pyo3::types::PyList::empty(py);
        for row in rows {
            let d = PyDict::new(py);
            d.set_item("name", row.name)?;
            d.set_item("passed", row.passed)?;
            d.set_item("detail", row.detail)?;
            d.set_item("code", row.code)?;
            list.append(d)?;
        }
        Ok(list.into_any().unbind())
    }

    /// Perform full bidirectional sync with a peer
    fn sync_with_peer(&self, py: Python<'_>, peer_id: &str) -> PyResult<PySyncResult> {
        let result = self.run(py, self.inner.sync_with_peer(peer_id));
        Ok(PySyncResult::from(result))
    }

    /// Deliver: sync, then send the recordings the peer lacks.
    fn deliver(&self, py: Python<'_>, peer_id: &str) -> PyResult<PySyncResult> {
        Ok(PySyncResult::from(self.run(py, self.inner.deliver(peer_id))))
    }

    /// Exchange: sync, then send and fetch.
    fn exchange(&self, py: Python<'_>, peer_id: &str) -> PyResult<PySyncResult> {
        Ok(PySyncResult::from(self.run(py, self.inner.exchange(peer_id))))
    }

    /// Send the recordings the peer lacks, without a sync.
    fn send_to_peer(&self, py: Python<'_>, peer_id: &str) -> PyResult<PySyncResult> {
        Ok(PySyncResult::from(self.run(py, self.inner.send_to_peer(peer_id))))
    }

    /// Fetch the recordings this device lacks from the peer, without a sync.
    fn fetch_from_peer(&self, py: Python<'_>, peer_id: &str) -> PyResult<PySyncResult> {
        Ok(PySyncResult::from(self.run(py, self.inner.fetch_from_peer(peer_id))))
    }

    /// Pull changes from a peer (one-way)
    fn pull_from_peer(&self, py: Python<'_>, peer_id: &str) -> PyResult<PySyncResult> {
        let result = self.run(py, self.inner.pull_from_peer(peer_id));
        Ok(PySyncResult::from(result))
    }

    /// Push changes to a peer (one-way)
    fn push_to_peer(&self, py: Python<'_>, peer_id: &str) -> PyResult<PySyncResult> {
        let result = self.run(py, self.inner.push_to_peer(peer_id));
        Ok(PySyncResult::from(result))
    }

    /// Perform initial sync (full dataset transfer) with a peer
    fn initial_sync(&self, py: Python<'_>, peer_id: &str) -> PyResult<PySyncResult> {
        let result = self.run(py, self.inner.initial_sync(peer_id));
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

    /// Fetch one recording from a peer
    /// Returns a dict with {"success": bool, "bytes": int} or {"success": false, "error": str}
    fn fetch_audio_file(&self, py: Python<'_>, peer_url: &str, audio_id: &str, dest_path: &str) -> PyResult<PyObject> {
        let dest = std::path::Path::new(dest_path);
        let result = self.runtime.block_on(
            self.inner.fetch_audio_file(peer_url, audio_id, dest, 0, 0, 1)
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

    /// Send one recording to a peer
    /// Returns a dict with {"success": bool, "bytes": int} or {"success": false, "error": str}
    fn send_audio_file(&self, py: Python<'_>, peer_url: &str, audio_id: &str, source_path: &str) -> PyResult<PyObject> {
        let source = std::path::Path::new(source_path);
        let result = self.runtime.block_on(
            self.inner.send_audio_file(peer_url, audio_id, source)
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

}

/// Make sure this installation has a device key for its account and that
/// its own card is in the database (AUTH-1). Called at every start.
/// Returns the device id.
fn account_entry<'py>(py: Python<'py>, e: &voicecore_lib::accounts::AccountEntry, directory: &std::path::Path) -> PyResult<PyObject> {
    let d = PyDict::new(py);
    d.set_item("account_id", e.account_id.clone())?;
    d.set_item("label", e.label.clone())?;
    d.set_item("is_default", e.is_default)?;
    d.set_item("hosted", e.hosted)?;
    d.set_item("created_at", e.created_at)?;
    d.set_item("last_opened_at", e.last_opened_at)?;
    d.set_item("directory", directory.to_string_lossy().to_string())?;
    Ok(d.into_any().unbind())
}

/// Which account `root` opens for `selector` (ACCT-6). Returns a dict with
/// mode ("single" or "account"), directory, root and, for an account, its
/// account_id and label.
#[pyfunction]
#[pyo3(signature = (root, selector=None, create_default=true))]
fn resolve_account<'py>(py: Python<'py>, root: &str, selector: Option<&str>, create_default: bool) -> PyResult<PyObject> {
    let resolved = voicecore_lib::accounts::resolve(std::path::Path::new(root), selector, create_default).map_err(voice_error_to_pyerr)?;
    let d = PyDict::new(py);
    d.set_item("directory", resolved.directory().to_string_lossy().to_string())?;
    d.set_item("root", resolved.root().to_string_lossy().to_string())?;
    match &resolved {
        voicecore_lib::accounts::Resolved::Single { .. } => {
            d.set_item("mode", "single")?;
        }
        voicecore_lib::accounts::Resolved::Account { entry, .. } => {
            d.set_item("mode", "account")?;
            d.set_item("account_id", entry.account_id.clone())?;
            d.set_item("label", entry.label.clone())?;
            d.set_item("hosted", entry.hosted)?;
        }
    }
    Ok(d.into_any().unbind())
}

/// Every account of the root's index, default first.
#[pyfunction]
fn account_list<'py>(py: Python<'py>, root: &str) -> PyResult<PyObject> {
    let index = voicecore_lib::accounts::AccountIndex::open(std::path::Path::new(root)).map_err(voice_error_to_pyerr)?;
    let list = PyList::empty(py);
    for e in index.list().map_err(voice_error_to_pyerr)? {
        list.append(account_entry(py, &e, &index.directory(&e.account_id))?)?;
    }
    Ok(list.into_any().unbind())
}

/// Make a new account under the root (ACCT-7).
#[pyfunction]
#[pyo3(signature = (root, label=None, hosted=false))]
fn account_create<'py>(py: Python<'py>, root: &str, label: Option<&str>, hosted: bool) -> PyResult<PyObject> {
    let index = voicecore_lib::accounts::AccountIndex::open(std::path::Path::new(root)).map_err(voice_error_to_pyerr)?;
    let e = index.create(label, hosted).map_err(voice_error_to_pyerr)?;
    account_entry(py, &e, &index.directory(&e.account_id))
}

/// Register an account whose id is known (one joined or hosted).
#[pyfunction]
#[pyo3(signature = (root, account_id, label, hosted=false))]
fn account_register<'py>(py: Python<'py>, root: &str, account_id: &str, label: &str, hosted: bool) -> PyResult<PyObject> {
    let index = voicecore_lib::accounts::AccountIndex::open(std::path::Path::new(root)).map_err(voice_error_to_pyerr)?;
    let e = index.register(account_id, label, hosted).map_err(voice_error_to_pyerr)?;
    account_entry(py, &e, &index.directory(&e.account_id))
}

#[pyfunction]
fn account_set_default(root: &str, selector: &str) -> PyResult<()> {
    let index = voicecore_lib::accounts::AccountIndex::open(std::path::Path::new(root)).map_err(voice_error_to_pyerr)?;
    index.set_default(selector).map_err(voice_error_to_pyerr)
}

#[pyfunction]
fn account_set_hosted(root: &str, selector: &str, hosted: bool) -> PyResult<()> {
    let index = voicecore_lib::accounts::AccountIndex::open(std::path::Path::new(root)).map_err(voice_error_to_pyerr)?;
    index.set_hosted(selector, hosted).map_err(voice_error_to_pyerr)
}

/// Forget an account: the index row only; its directory stays.
#[pyfunction]
fn account_remove(root: &str, selector: &str) -> PyResult<()> {
    let index = voicecore_lib::accounts::AccountIndex::open(std::path::Path::new(root)).map_err(voice_error_to_pyerr)?;
    index.remove(selector).map_err(voice_error_to_pyerr)
}

/// Show a code (PAIR-1): make a token and return the setup text. `urls`
/// are where this installation listens.
#[pyfunction]
#[pyo3(signature = (urls, config_dir=None))]
fn pairing_offer(urls: Vec<String>, config_dir: Option<&str>) -> PyResult<String> {
    let config_path = config_dir.map(std::path::PathBuf::from);
    let cfg = config::Config::new(config_path).map_err(voice_error_to_pyerr)?;
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;
    let setup = voicecore_lib::pairing::offer(&db, &cfg, urls).map_err(voice_error_to_pyerr)?;
    Ok(setup.to_text())
}

/// Show a grant text (PAIR-5): a token with which a holder gives this
/// server, which holds no account of its own, an account to host. The root
/// gets an index if it has none; no default account is made.
#[pyfunction]
#[pyo3(signature = (root, urls, label=None))]
fn hosting_offer(root: &str, urls: Vec<String>, label: Option<&str>) -> PyResult<String> {
    let root = std::path::Path::new(root);
    let index = voicecore_lib::accounts::AccountIndex::open(root).map_err(voice_error_to_pyerr)?;
    let cfg = config::Config::new(Some(root.to_path_buf())).map_err(voice_error_to_pyerr)?;
    let setup = voicecore_lib::pairing::offer_hosting(&index, &cfg, label, urls).map_err(voice_error_to_pyerr)?;
    Ok(setup.to_text())
}

/// Hide the code: withdraw the offer.
#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn pairing_withdraw(config_dir: Option<&str>) -> PyResult<()> {
    let config_path = config_dir.map(std::path::PathBuf::from);
    let cfg = config::Config::new(config_path).map_err(voice_error_to_pyerr)?;
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;
    voicecore_lib::pairing::withdraw(&db).map_err(voice_error_to_pyerr)
}

/// Where a listener on this machine is reachable, for a code or a person.
#[pyfunction]
#[pyo3(signature = (port, host="0.0.0.0", plain_http=false))]
fn listen_urls(port: u16, host: &str, plain_http: bool) -> Vec<String> {
    sync_server::listen_urls(host, port, plain_http)
}

/// The hash a card holds for a device key (hex SHA-256).
#[pyfunction]
fn device_key_hash(key: &str) -> String {
    voicecore_lib::auth::key_hash(key)
}

#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn ensure_own_device_card(config_dir: Option<&str>) -> PyResult<String> {
    let config_path = config_dir.map(std::path::PathBuf::from);
    let mut cfg = config::Config::new(config_path).map_err(voice_error_to_pyerr)?;
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;
    let card = voicecore_lib::auth::ensure_own_device_card(&db, &mut cfg).map_err(voice_error_to_pyerr)?;
    Ok(card.device_id)
}

/// The fingerprint of this installation's listener certificate, making the
/// certificate if there is none yet. What another device pins.
#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn certificate_fingerprint(config_dir: Option<&str>) -> PyResult<String> {
    let config_path = config_dir.map(std::path::PathBuf::from);
    let cfg = config::Config::new(config_path).map_err(voice_error_to_pyerr)?;
    let (_, _, fingerprint) = voicecore_lib::tls::ensure_server_certificate(&cfg, false).map_err(voice_error_to_pyerr)?;
    Ok(fingerprint)
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
    let results = py.allow_threads(|| runtime.block_on(sync_client::sync_all_peers(db_arc, config_arc)));

    // Convert to Python dict
    let dict = PyDict::new(py);
    for (peer_id, result) in results {
        let py_result = PySyncResult::from(result);
        dict.set_item(peer_id, py_result.into_pyobject(py)?)?;
    }
    Ok(dict.into_any().unbind())
}

// ============================================================================
// File Storage wrappers
// ============================================================================

/// Result of uploading pending audio files
#[pyclass(name = "UploadPendingResult")]
pub struct PyUploadPendingResult {
    #[pyo3(get)]
    uploaded: usize,
    /// Pending records whose file is not on this device (another device owns them)
    #[pyo3(get)]
    skipped: usize,
    #[pyo3(get)]
    failed: usize,
    /// Files not attempted because an earlier remote failure stopped the batch
    #[pyo3(get)]
    deferred: usize,
    #[pyo3(get)]
    errors: Vec<String>,
}

/// Result of downloading audio files from cloud storage
#[pyclass(name = "DownloadResult")]
pub struct PyDownloadResult {
    #[pyo3(get)]
    downloaded: usize,
    #[pyo3(get)]
    already_local: usize,
    #[pyo3(get)]
    not_in_cloud: usize,
    #[pyo3(get)]
    failed: usize,
    #[pyo3(get)]
    deferred: usize,
    #[pyo3(get)]
    errors: Vec<String>,
}

impl From<file_storage::DownloadMissingResult> for PyDownloadResult {
    fn from(r: file_storage::DownloadMissingResult) -> Self {
        Self {
            downloaded: r.downloaded,
            already_local: r.already_local,
            not_in_cloud: r.not_in_cloud,
            failed: r.failed,
            deferred: r.deferred,
            errors: r.errors,
        }
    }
}

/// Open config, database and audio directory for a cloud storage operation.
fn cloud_context(
    config_dir: Option<&str>,
) -> PyResult<(tokio::runtime::Runtime, database::Database, std::path::PathBuf, Option<voicecore_lib::crypto::RecordingKey>)> {
    let runtime = tokio::runtime::Runtime::new()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
    let config_path = config_dir.map(std::path::PathBuf::from);
    let cfg = config::Config::new(config_path).map_err(voice_error_to_pyerr)?;
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;
    let audiofile_dir = cfg.audiofile_directory().ok_or_else(|| {
        pyo3::exceptions::PyRuntimeError::new_err(
            "Audiofile directory not configured. Set it with 'cli config set audiofile_directory <path>'",
        )
    })?;
    let key = cfg.recording_key();
    Ok((runtime, db, std::path::PathBuf::from(audiofile_dir), key))
}

/// Download one audio file from cloud storage on demand.
///
/// Returns a dict: {"status": "downloaded" | "already_local" | "not_in_cloud", "bytes": int}
///
/// Raises:
///     RuntimeError: storage not configured, offline, object missing, etc.
#[pyfunction]
#[pyo3(signature = (audio_file_id, config_dir=None))]
fn download_audio_file_from_cloud<'py>(
    py: Python<'py>,
    audio_file_id: &str,
    config_dir: Option<&str>,
) -> PyResult<PyObject> {
    let (runtime, db, audiofile_dir, key) = cloud_context(config_dir)?;
    // The database moves into the closure: it is Send, not Sync, and the
    // interpreter lock is released while the download runs
    let outcome = py
        .allow_threads(move || runtime.block_on(file_storage::download_audio_file(&db, &audiofile_dir, audio_file_id, key.as_ref())))
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
    let dict = PyDict::new(py);
    match outcome {
        file_storage::DownloadOutcome::Downloaded(bytes) => {
            dict.set_item("status", "downloaded")?;
            dict.set_item("bytes", bytes)?;
        }
        file_storage::DownloadOutcome::AlreadyLocal => {
            dict.set_item("status", "already_local")?;
            dict.set_item("bytes", 0u64)?;
        }
        file_storage::DownloadOutcome::NotInCloud => {
            dict.set_item("status", "not_in_cloud")?;
            dict.set_item("bytes", 0u64)?;
        }
    }
    Ok(dict.into_any().unbind())
}

/// Download every audio file attached to a note that is in cloud storage but
/// not on this device.
#[pyfunction]
#[pyo3(signature = (note_id, config_dir=None))]
fn download_audio_files_for_note(py: Python<'_>, note_id: &str, config_dir: Option<&str>) -> PyResult<PyDownloadResult> {
    let (runtime, db, audiofile_dir, key) = cloud_context(config_dir)?;
    py.allow_threads(move || runtime.block_on(file_storage::download_audio_files_for_note(&db, &audiofile_dir, note_id, key.as_ref())))
        .map(PyDownloadResult::from)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

/// Download every non-deleted audio file that is in cloud storage but not on
/// this device (the "mirror everything" action).
#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn download_missing_audio_files(py: Python<'_>, config_dir: Option<&str>) -> PyResult<PyDownloadResult> {
    let (runtime, db, audiofile_dir, key) = cloud_context(config_dir)?;
    py.allow_threads(move || runtime.block_on(file_storage::download_missing_audio_files(&db, &audiofile_dir, key.as_ref())))
        .map(PyDownloadResult::from)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

/// Upload pending audio files to cloud storage (S3).
///
/// This function uploads all audio files that have not yet been uploaded to
/// cloud storage (storage_provider is NULL in the database).
///
/// Args:
///     config_dir: Path to config directory (optional, uses default if None)
///
/// Returns:
///     UploadPendingResult with counts of uploaded/failed files and error messages
///
/// Raises:
///     RuntimeError: If cloud storage is not configured or upload fails
#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn upload_pending_audio_files(py: Python<'_>, config_dir: Option<&str>) -> PyResult<PyUploadPendingResult> {
    // Create Tokio runtime
    let runtime = tokio::runtime::Runtime::new()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    // Create Config and Database from config_dir
    let config_path = config_dir.map(std::path::PathBuf::from);
    let cfg = config::Config::new(config_path).map_err(voice_error_to_pyerr)?;
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;

    // Get audiofile directory
    let audiofile_dir = cfg.audiofile_directory().ok_or_else(|| {
        pyo3::exceptions::PyRuntimeError::new_err(
            "Audiofile directory not configured. Set it with 'cli config set audiofile_directory <path>'",
        )
    })?;
    let audiofile_path = std::path::PathBuf::from(audiofile_dir);
    let key = cfg.recording_key();

    // Run the upload without the interpreter lock; the database moves in
    let result: Result<file_storage::UploadPendingResult, file_storage::FileStorageError> =
        py.allow_threads(move || runtime.block_on(file_storage::upload_pending_audio_files(&db, &audiofile_path, key.as_ref())));

    match result {
        Ok(r) => Ok(PyUploadPendingResult {
            uploaded: r.uploaded,
            skipped: r.skipped,
            failed: r.failed,
            deferred: r.deferred,
            errors: r.errors,
        }),
        Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(e.to_string())),
    }
}

/// The recording key's text (Stage 15, ENC-1), made now when the account has
/// none; showing it counts as the export the encryption switch waits for.
#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn recording_key_export(config_dir: Option<&str>) -> PyResult<String> {
    let mut cfg = config::Config::new(config_dir.map(std::path::PathBuf::from)).map_err(voice_error_to_pyerr)?;
    if cfg.recording_key_text().is_empty() {
        cfg.set_recording_key(&voicecore_lib::crypto::RecordingKey::generate().to_text()).map_err(voice_error_to_pyerr)?;
    }
    cfg.set_recording_key_exported(true).map_err(voice_error_to_pyerr)?;
    Ok(cfg.recording_key_text().to_string())
}

/// Keep a recording key from an export (ENC-1).
#[pyfunction]
#[pyo3(signature = (text, config_dir=None))]
fn recording_key_import(text: &str, config_dir: Option<&str>) -> PyResult<()> {
    let mut cfg = config::Config::new(config_dir.map(std::path::PathBuf::from)).map_err(voice_error_to_pyerr)?;
    cfg.set_recording_key(text).map_err(voice_error_to_pyerr)?;
    cfg.set_recording_key_exported(true).map_err(voice_error_to_pyerr)
}

/// Where encryption stands: has_key, exported, on.
#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn encryption_state<'py>(py: Python<'py>, config_dir: Option<&str>) -> PyResult<PyObject> {
    let cfg = config::Config::new(config_dir.map(std::path::PathBuf::from)).map_err(voice_error_to_pyerr)?;
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;
    let d = PyDict::new(py);
    d.set_item("has_key", !cfg.recording_key_text().is_empty())?;
    d.set_item("exported", cfg.recording_key_exported())?;
    d.set_item("on", db.encryption_on().map_err(voice_error_to_pyerr)?)?;
    Ok(d.into_any().unbind())
}

/// Turn encryption of new uploads on or off (ENC-3); on needs the key exported here first.
#[pyfunction]
#[pyo3(signature = (on, config_dir=None))]
fn set_encryption_on(on: bool, config_dir: Option<&str>) -> PyResult<()> {
    let cfg = config::Config::new(config_dir.map(std::path::PathBuf::from)).map_err(voice_error_to_pyerr)?;
    if on && (cfg.recording_key_text().is_empty() || !cfg.recording_key_exported()) {
        return Err(pyo3::exceptions::PyRuntimeError::new_err("Export the recording key first: without it these recordings cannot be played"));
    }
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;
    db.set_encryption_on(on).map_err(voice_error_to_pyerr)
}

/// "Re-upload existing recordings encrypted" (ENC-3).
#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn reupload_encrypted(py: Python<'_>, config_dir: Option<&str>) -> PyResult<PyUploadPendingResult> {
    let (runtime, db, audiofile_dir, key) = cloud_context(config_dir)?;
    let result = py.allow_threads(move || runtime.block_on(file_storage::reupload_encrypted(&db, &audiofile_dir, None, None, key.as_ref())));
    match result {
        Ok(r) => Ok(PyUploadPendingResult { uploaded: r.uploaded, skipped: r.skipped, failed: r.failed, deferred: r.deferred, errors: r.errors }),
        Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(e.to_string())),
    }
}

// ============================================================================
// Sync server wrappers
// ============================================================================

/// Start the sync server (blocking).
///
/// This function blocks until the server is stopped (via stop_sync_server or Ctrl+C).
///
/// Args:
///     config_dir: the one account directory to serve; None with `root` set
///     port: Port to listen on (optional, uses config default if None)
///     verbose: Enable verbose logging to stdout (default: False)
///     ansi_colors: Enable ANSI color codes in log output (default: True)
///     root: an indexed root: every account in it is served, each opened on
///         its first request (Stage 3, hosting); `config_dir` is ignored
#[pyfunction]
#[pyo3(signature = (config_dir=None, host="0.0.0.0", port=None, plain_http=false, verbose=false, ansi_colors=true, root=None))]
fn start_sync_server(
    py: Python<'_>,
    config_dir: Option<&str>,
    host: &str,
    port: Option<u16>,
    plain_http: bool,
    verbose: bool,
    ansi_colors: bool,
    root: Option<&str>,
) -> PyResult<()> {
    // Initialize tracing subscriber for logging output only if verbose is enabled
    if verbose {
        use tracing_subscriber::{fmt, EnvFilter};
        // Use EnvFilter to explicitly set DEBUG level for all targets
        // This overrides any RUST_LOG environment variable
        let filter = EnvFilter::new("debug");
        let _ = fmt()
            .with_env_filter(filter)
            .with_target(false)
            .with_ansi(ansi_colors)
            .try_init();
    }

    // Create Tokio runtime
    let runtime = tokio::runtime::Runtime::new()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    if let Some(root) = root {
        let root_path = std::path::PathBuf::from(root);
        let machine = config::Config::new(Some(root_path.clone())).map_err(voice_error_to_pyerr)?;
        let server_port = port.unwrap_or_else(|| machine.sync_server_port());
        let served = voicecore_lib::accounts::AccountIndex::open(&root_path)
            .and_then(|i| i.list())
            .map_err(voice_error_to_pyerr)?;
        println!("Starting the sync server for every account of {}...", root);
        println!("  Device ID:   {}", machine.device_id_hex());
        println!("  Device Name: {}", machine.device_name());
        println!("  Listening:   {}://{}:{}", if plain_http { "http" } else { "https" }, host, server_port);
        if served.is_empty() {
            println!("  Accounts:    none yet; 'account host' prints the text a holder needs to grant one");
        }
        for a in &served {
            println!("  Account:     {} ({}{})", a.account_id, a.label, if a.hosted { ", hosted" } else { "" });
        }
        println!("  Press Ctrl-C to stop");
        println!();
        py.allow_threads(|| {
            runtime.block_on(async {
                tokio::spawn(async {
                    if let Ok(()) = tokio::signal::ctrl_c().await {
                        println!("\nReceived Ctrl-C, shutting down...");
                        sync_server::stop_server();
                    }
                });
                sync_server::start_hosting_server(&root_path, host, server_port, plain_http).await
            })
        })
        .map_err(voice_error_to_pyerr)?;
        return Ok(());
    }

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
    println!("  Listening:   {}://{}:{}", if plain_http { "http" } else { "https" }, host, server_port);
    println!("  Account:     {}", db.account_id().unwrap_or_default());
    println!("  Endpoints:   /sync/status, /sync/changes, /sync/full, /sync/apply");
    if verbose {
        println!("  Logging:     enabled (verbose mode)");
    }
    println!("  Press Ctrl-C to stop");
    println!();

    // Wrap in Arc<Mutex<>> for sync_server
    let db_arc = Arc::new(Mutex::new(db));
    let config_arc = Arc::new(Mutex::new(cfg));

    // Run server with Ctrl-C handler, without holding the interpreter lock:
    // the interface that started the listener on a thread stays alive
    py.allow_threads(|| {
        runtime.block_on(async {
            // Spawn task to handle Ctrl-C
            tokio::spawn(async {
                if let Ok(()) = tokio::signal::ctrl_c().await {
                    println!("\nReceived Ctrl-C, shutting down...");
                    sync_server::stop_server();
                }
            });

            // Run the server
            sync_server::start_server(db_arc, config_arc, host, server_port, plain_http).await
        })
    })
    .map_err(voice_error_to_pyerr)?;

    Ok(())
}

/// The periodic backup, now (SNAP-5): every account of a root, or the one
/// account of a directory. Returns the copies made; raises when any account
/// could not be copied.
#[pyfunction]
#[pyo3(signature = (config_dir=None, root=None))]
fn backup_now(py: Python<'_>, config_dir: Option<&str>, root: Option<&str>) -> PyResult<Vec<String>> {
    let source: Arc<dyn sync_server::AccountSource> = match (root, config_dir) {
        (Some(root), _) if voicecore_lib::accounts::AccountIndex::exists(std::path::Path::new(root)) => {
            use sync_server::AccountSource;
            let source = sync_server::IndexedAccounts::new(std::path::Path::new(root), Vec::new());
            for account in source.served() {
                source.account(&account);
            }
            Arc::new(source)
        }
        (_, Some(dir)) => {
            let cfg = config::Config::new(Some(std::path::PathBuf::from(dir))).map_err(voice_error_to_pyerr)?;
            let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;
            let account_id = db.account_id().map_err(voice_error_to_pyerr)?;
            Arc::new(sync_server::SingleAccount { account_id, handle: sync_server::AccountHandle { db: Arc::new(Mutex::new(db)), config: Arc::new(Mutex::new(cfg)) } })
        }
        _ => return Err(pyo3::exceptions::PyValueError::new_err("Give a config_dir or a root")),
    };
    let keep = match config_dir {
        Some(dir) => config::Config::new(Some(std::path::PathBuf::from(dir))).map_err(voice_error_to_pyerr)?.backup().keep as usize,
        None => config::Config::new(root.map(std::path::PathBuf::from)).map_err(voice_error_to_pyerr)?.backup().keep as usize,
    };
    let (made, failed) = py.allow_threads(move || sync_server::backup_open_accounts(source.as_ref(), keep));
    if !failed.is_empty() {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(failed.join("; ")));
    }
    Ok(made.into_iter().map(|p| p.to_string_lossy().to_string()).collect())
}

/// Whether an account's periodic backup is due: no copy yet, or the newest
/// older than the interval.
#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn backup_due(config_dir: Option<&str>) -> PyResult<bool> {
    let cfg = config::Config::new(config_dir.map(std::path::PathBuf::from)).map_err(voice_error_to_pyerr)?;
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;
    let account_id = db.account_id().map_err(voice_error_to_pyerr)?;
    Ok(sync_server::backup_due(&cfg, &account_id))
}

/// Whether a listener runs in this process.
#[pyfunction]
fn sync_server_running() -> bool {
    sync_server::server_running()
}

/// Seconds since the listener last served a request or started; None when
/// no listener has run in this process (Stage 6: the idle stop).
#[pyfunction]
fn listener_idle_seconds() -> Option<u64> {
    sync_server::idle_seconds()
}

// ---------------------------------------------------------------------------
// The bucket, made and hardened (Stage 8, Stage 14)
// ---------------------------------------------------------------------------

fn bucket_key(access_key_id: &str, secret_access_key: &str, region: &str, endpoint: Option<&str>) -> voicecore_lib::bucket_setup::BucketKey {
    voicecore_lib::bucket_setup::BucketKey {
        access_key_id: access_key_id.to_string(),
        secret_access_key: secret_access_key.to_string(),
        region: region.to_string(),
        endpoint: endpoint.map(|e| e.trim_end_matches('/').to_string()).filter(|e| !e.is_empty()),
    }
}

fn check_rows_to_py<'py>(py: Python<'py>, rows: Vec<voicecore_lib::sync_protocol::CheckRow>) -> PyResult<PyObject> {
    let list = PyList::empty(py);
    for row in rows {
        let d = PyDict::new(py);
        d.set_item("name", row.name)?;
        d.set_item("passed", row.passed)?;
        d.set_item("detail", row.detail)?;
        d.set_item("code", row.code)?;
        list.append(d)?;
    }
    Ok(list.into_any().unbind())
}

fn bucket_runtime() -> PyResult<tokio::runtime::Runtime> {
    tokio::runtime::Runtime::new().map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

/// The policy text the wizard shows for the console.
#[pyfunction]
fn bucket_policy_text() -> String {
    voicecore_lib::bucket_setup::policy_text()
}

/// A pasted key id or secret without its label and whitespace.
#[pyfunction]
fn bucket_clean_key_id(text: &str) -> String {
    voicecore_lib::bucket_setup::clean_key_id(text)
}

#[pyfunction]
fn bucket_clean_secret(text: &str) -> String {
    voicecore_lib::bucket_setup::clean_secret(text)
}

/// A bucket name nobody has yet, most likely.
#[pyfunction]
fn bucket_suggest_name() -> String {
    voicecore_lib::bucket_setup::suggest_bucket_name()
}

/// Whether a name may be a bucket's: None, or the sentence that says why not.
#[pyfunction]
fn bucket_name_problem(name: &str) -> Option<String> {
    voicecore_lib::bucket_setup::bucket_name_allowed(name).err()
}

/// What a failure means, in words.
#[pyfunction]
fn bucket_explain_error(text: &str) -> String {
    voicecore_lib::bucket_setup::explain_error(text)
}

/// The regions the wizard offers.
#[pyfunction]
fn bucket_regions() -> Vec<String> {
    voicecore_lib::bucket_setup::REGIONS.iter().map(|r| r.to_string()).collect()
}

/// The region whose endpoint answers fastest, or None when none answers.
#[pyfunction]
#[pyo3(signature = (regions=None))]
fn bucket_nearest_region(py: Python<'_>, regions: Option<Vec<String>>) -> PyResult<Option<String>> {
    let regions: Vec<String> = regions.unwrap_or_else(|| voicecore_lib::bucket_setup::REGIONS.iter().map(|r| r.to_string()).collect());
    let refs: Vec<&str> = regions.iter().map(String::as_str).collect();
    Ok(bucket_runtime()?.block_on(voicecore_lib::bucket_setup::nearest_region(&refs)))
}

/// Whether a bucket of this name answers this key; raises with the reason when the answer is neither.
#[pyfunction]
#[pyo3(signature = (access_key_id, secret_access_key, region, name, endpoint=None))]
fn bucket_exists(py: Python<'_>, access_key_id: &str, secret_access_key: &str, region: &str, name: &str, endpoint: Option<&str>) -> PyResult<bool> {
    let key = bucket_key(access_key_id, secret_access_key, region, endpoint);
    py.allow_threads(|| bucket_runtime().map(|r| r.block_on(voicecore_lib::bucket_setup::bucket_exists(&key, name))))?.map_err(pyo3::exceptions::PyRuntimeError::new_err)
}

/// Make the bucket, private.
#[pyfunction]
#[pyo3(signature = (access_key_id, secret_access_key, region, name, endpoint=None))]
fn bucket_create(py: Python<'_>, access_key_id: &str, secret_access_key: &str, region: &str, name: &str, endpoint: Option<&str>) -> PyResult<()> {
    let key = bucket_key(access_key_id, secret_access_key, region, endpoint);
    py.allow_threads(|| bucket_runtime().map(|r| r.block_on(voicecore_lib::bucket_setup::create_bucket(&key, name))))?.map_err(pyo3::exceptions::PyRuntimeError::new_err)
}

/// Block public access, default encryption, TLS only: one row each, verified.
#[pyfunction]
#[pyo3(signature = (access_key_id, secret_access_key, region, name, endpoint=None))]
fn bucket_harden<'py>(py: Python<'py>, access_key_id: &str, secret_access_key: &str, region: &str, name: &str, endpoint: Option<&str>) -> PyResult<PyObject> {
    let key = bucket_key(access_key_id, secret_access_key, region, endpoint);
    let rows = py.allow_threads(|| bucket_runtime().map(|r| r.block_on(voicecore_lib::bucket_setup::harden_bucket(&key, name))))?;
    check_rows_to_py(py, rows)
}

/// The three lifecycle rules.
#[pyfunction]
#[pyo3(signature = (access_key_id, secret_access_key, region, name, endpoint=None))]
fn bucket_set_lifecycle(py: Python<'_>, access_key_id: &str, secret_access_key: &str, region: &str, name: &str, endpoint: Option<&str>) -> PyResult<()> {
    let key = bucket_key(access_key_id, secret_access_key, region, endpoint);
    py.allow_threads(|| bucket_runtime().map(|r| r.block_on(voicecore_lib::bucket_setup::set_lifecycle(&key, name))))?.map_err(pyo3::exceptions::PyRuntimeError::new_err)
}

/// Write a small object, read it back, compare, tag it purged. Returns its key.
#[pyfunction]
#[pyo3(signature = (access_key_id, secret_access_key, region, name, endpoint=None, prefix=None))]
fn bucket_round_trip(py: Python<'_>, access_key_id: &str, secret_access_key: &str, region: &str, name: &str, endpoint: Option<&str>, prefix: Option<&str>) -> PyResult<String> {
    let key = bucket_key(access_key_id, secret_access_key, region, endpoint);
    py.allow_threads(|| bucket_runtime().map(|r| r.block_on(voicecore_lib::bucket_setup::round_trip(&key, name, prefix))))?.map_err(pyo3::exceptions::PyRuntimeError::new_err)
}

/// The bucket as it is, with a given key.
#[pyfunction]
#[pyo3(signature = (access_key_id, secret_access_key, region, name, endpoint=None, prefix=None))]
fn bucket_check_with<'py>(py: Python<'py>, access_key_id: &str, secret_access_key: &str, region: &str, name: &str, endpoint: Option<&str>, prefix: Option<&str>) -> PyResult<PyObject> {
    let key = bucket_key(access_key_id, secret_access_key, region, endpoint);
    let rows = py.allow_threads(|| bucket_runtime().map(|r| r.block_on(voicecore_lib::bucket_setup::check_bucket(&key, name, prefix))))?;
    check_rows_to_py(py, rows)
}

/// The bucket as it is, with the saved configuration of an account directory.
#[pyfunction]
#[pyo3(signature = (config_dir=None))]
fn bucket_check<'py>(py: Python<'py>, config_dir: Option<&str>) -> PyResult<PyObject> {
    let config_path = config_dir.map(std::path::PathBuf::from);
    let cfg = config::Config::new(config_path).map_err(voice_error_to_pyerr)?;
    let db = database::Database::new(cfg.database_file()).map_err(voice_error_to_pyerr)?;
    let saved = db.get_file_storage_config_struct().map_err(voice_error_to_pyerr)?;
    if !saved.is_enabled() {
        let list = PyList::empty(py);
        let d = PyDict::new(py);
        d.set_item("name", "Bucket")?;
        d.set_item("passed", false)?;
        d.set_item("detail", "No bucket is configured; run the storage wizard")?;
        d.set_item("code", "")?;
        list.append(d)?;
        return Ok(list.into_any().unbind());
    }
    let key = bucket_key(
        saved.s3_access_key_id().unwrap_or_default(),
        saved.s3_secret_access_key().unwrap_or_default(),
        saved.s3_region().unwrap_or_default(),
        saved.s3_endpoint(),
    );
    let name = saved.s3_bucket().unwrap_or_default().to_string();
    let prefix = saved.s3_prefix().map(String::from);
    let rows = py.allow_threads(|| bucket_runtime().map(|r| r.block_on(voicecore_lib::bucket_setup::check_bucket(&key, &name, prefix.as_deref()))))?;
    check_rows_to_py(py, rows)
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
#[pyo3(signature = (db, changes, peer_device_id, peer_device_name=None, local_device_id=None, local_device_name=None))]
fn apply_sync_changes<'py>(
    py: Python<'py>,
    db: &PyDatabase,
    changes: pyo3::Bound<'py, PyList>,
    peer_device_id: &str,
    peer_device_name: Option<&str>,
    local_device_id: Option<&str>,
    local_device_name: Option<&str>,
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
                let timestamp: i64 = change_dict
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
                let timestamp: i64 = change_item.getattr("timestamp")?.extract()?;
                let device_id: String = change_item.getattr("device_id")?.extract()?;
                let device_name: Option<String> = change_item
                    .getattr("device_name")
                    .ok()
                    .and_then(|v| v.extract().ok());
                let data_obj = change_item.getattr("data")?;
                let data_json = pydict_to_json_value(py, &data_obj)?;
                (entity_type, entity_id, operation, timestamp, device_id, device_name, data_json)
            };

        rust_changes.push(models::SyncChange {
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
        local_device_id,
        local_device_name,
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

#[pyfunction]
#[pyo3(name = "resolve_tag_term")]
fn py_resolve_tag_term(db: &PyDatabase, tag_term: &str) -> PyResult<(Vec<String>, bool, bool)> {
    let db_ref = db.inner_ref()?;
    let (tag_ids, is_ambiguous, not_found) = search::resolve_tag_term(db_ref, tag_term)
        .map_err(voice_error_to_pyerr)?;
    Ok((tag_ids, is_ambiguous, not_found))
}

#[pyfunction]
#[pyo3(name = "get_tag_full_path")]
fn py_get_tag_full_path(db: &PyDatabase, tag_id: &str) -> PyResult<String> {
    let db_ref = db.inner_ref()?;
    search::get_tag_full_path(db_ref, tag_id).map_err(voice_error_to_pyerr)
}

#[pyfunction]
#[pyo3(name = "find_ambiguous_tags")]
fn py_find_ambiguous_tags(db: &PyDatabase, tag_terms: Vec<String>) -> PyResult<Vec<String>> {
    let db_ref = db.inner_ref()?;
    search::find_ambiguous_tags(db_ref, &tag_terms).map_err(voice_error_to_pyerr)
}

#[pyfunction]
#[pyo3(name = "build_tag_search_term")]
#[pyo3(signature = (db, tag_id, use_full_path=false))]
fn py_build_tag_search_term(db: &PyDatabase, tag_id: &str, use_full_path: bool) -> PyResult<String> {
    let db_ref = db.inner_ref()?;
    search::build_tag_search_term(db_ref, tag_id, use_full_path).map_err(voice_error_to_pyerr)
}

// ============================================================================
// Merge/Conflict functions
// ============================================================================

#[pyfunction]
#[pyo3(name = "diff3_merge")]
fn py_diff3_merge(base: &str, local: &str, remote: &str) -> PyResult<PyObject> {
    let result = merge::diff3_merge(base, local, remote);
    Python::with_gil(|py| {
        let dict = PyDict::new(py);
        dict.set_item("content", &result.content)?;
        dict.set_item("has_conflicts", result.has_conflicts)?;
        dict.set_item("conflict_count", result.conflict_count)?;
        Ok(dict.into_any().unbind())
    })
}

#[pyfunction]
#[pyo3(name = "auto_merge_if_possible")]
fn py_auto_merge_if_possible(local: &str, remote: &str, base: Option<&str>) -> Option<String> {
    merge::auto_merge_if_possible(local, remote, base)
}

#[pyfunction]
#[pyo3(name = "get_diff_preview")]
fn py_get_diff_preview(local: &str, remote: &str) -> String {
    merge::get_diff_preview(local, remote)
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

/// Human-readable name stamped on every version this device creates, so that
/// conflicts can say which devices disagreed.
#[pyfunction]
#[pyo3(name = "set_local_device_name")]
fn py_set_local_device_name(name: &str) -> PyResult<()> {
    database::set_local_device_name(name);
    Ok(())
}

/// Tell the core which timezone this device is in, so that every timestamp it
/// writes also records the clock the user was reading. Call it at start and
/// whenever the timezone changes.
#[pyfunction]
#[pyo3(name = "set_local_timezone", signature = (offset_seconds, name=None))]
fn py_set_local_timezone(offset_seconds: i32, name: Option<String>) -> PyResult<()> {
    voicecore_lib::timezone::set_local_timezone(offset_seconds, name);
    Ok(())
}

#[pyfunction]
#[pyo3(name = "get_local_device_name")]
fn py_get_local_device_name() -> Option<String> {
    database::get_local_device_name()
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
    m.add_function(wrap_pyfunction!(ensure_own_device_card, m)?)?;
    m.add_function(wrap_pyfunction!(certificate_fingerprint, m)?)?;
    m.add_function(wrap_pyfunction!(device_key_hash, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_account, m)?)?;
    m.add_function(wrap_pyfunction!(account_list, m)?)?;
    m.add_function(wrap_pyfunction!(account_create, m)?)?;
    m.add_function(wrap_pyfunction!(account_register, m)?)?;
    m.add_function(wrap_pyfunction!(account_set_default, m)?)?;
    m.add_function(wrap_pyfunction!(account_set_hosted, m)?)?;
    m.add_function(wrap_pyfunction!(account_remove, m)?)?;
    m.add_function(wrap_pyfunction!(pairing_offer, m)?)?;
    m.add_function(wrap_pyfunction!(hosting_offer, m)?)?;
    m.add_function(wrap_pyfunction!(pairing_withdraw, m)?)?;
    m.add_function(wrap_pyfunction!(listen_urls, m)?)?;
    m.add_function(wrap_pyfunction!(stop_sync_server, m)?)?;
    m.add_function(wrap_pyfunction!(sync_server_running, m)?)?;
    m.add_function(wrap_pyfunction!(listener_idle_seconds, m)?)?;
    m.add_function(wrap_pyfunction!(backup_now, m)?)?;
    m.add_function(wrap_pyfunction!(backup_due, m)?)?;
    for f in [
        wrap_pyfunction!(bucket_policy_text, m)?,
        wrap_pyfunction!(bucket_clean_key_id, m)?,
        wrap_pyfunction!(bucket_clean_secret, m)?,
        wrap_pyfunction!(bucket_suggest_name, m)?,
        wrap_pyfunction!(bucket_name_problem, m)?,
        wrap_pyfunction!(bucket_explain_error, m)?,
        wrap_pyfunction!(bucket_regions, m)?,
        wrap_pyfunction!(bucket_nearest_region, m)?,
        wrap_pyfunction!(bucket_exists, m)?,
        wrap_pyfunction!(bucket_create, m)?,
        wrap_pyfunction!(bucket_harden, m)?,
        wrap_pyfunction!(bucket_set_lifecycle, m)?,
        wrap_pyfunction!(bucket_round_trip, m)?,
        wrap_pyfunction!(bucket_check_with, m)?,
        wrap_pyfunction!(bucket_check, m)?,
    ] {
        m.add_function(f)?;
    }
    m.add_function(wrap_pyfunction!(apply_sync_changes, m)?)?;

    // Register file storage functions
    m.add_class::<PyUploadPendingResult>()?;
    m.add_function(wrap_pyfunction!(upload_pending_audio_files, m)?)?;
    m.add_function(wrap_pyfunction!(recording_key_export, m)?)?;
    m.add_function(wrap_pyfunction!(recording_key_import, m)?)?;
    m.add_function(wrap_pyfunction!(encryption_state, m)?)?;
    m.add_function(wrap_pyfunction!(set_encryption_on, m)?)?;
    m.add_function(wrap_pyfunction!(reupload_encrypted, m)?)?;
    m.add_class::<PyDownloadResult>()?;
    m.add_function(wrap_pyfunction!(download_audio_file_from_cloud, m)?)?;
    m.add_function(wrap_pyfunction!(download_audio_files_for_note, m)?)?;
    m.add_function(wrap_pyfunction!(download_missing_audio_files, m)?)?;

    // Register search classes and functions
    m.add_class::<PySearchResult>()?;
    m.add_class::<PyParsedSearch>()?;
    m.add_function(wrap_pyfunction!(py_parse_search_input, m)?)?;
    m.add_function(wrap_pyfunction!(py_execute_search, m)?)?;
    m.add_function(wrap_pyfunction!(py_resolve_tag_term, m)?)?;
    m.add_function(wrap_pyfunction!(py_get_tag_full_path, m)?)?;
    m.add_function(wrap_pyfunction!(py_find_ambiguous_tags, m)?)?;
    m.add_function(wrap_pyfunction!(py_build_tag_search_term, m)?)?;

    // Register merge classes and functions
    m.add_class::<PyMergeResult>()?;
    m.add_function(wrap_pyfunction!(py_merge_content, m)?)?;
    m.add_function(wrap_pyfunction!(py_diff3_merge, m)?)?;
    m.add_function(wrap_pyfunction!(py_auto_merge_if_possible, m)?)?;
    m.add_function(wrap_pyfunction!(py_get_diff_preview, m)?)?;

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
    m.add_function(wrap_pyfunction!(py_set_local_device_name, m)?)?;
    m.add_function(wrap_pyfunction!(py_get_local_device_name, m)?)?;
    m.add_function(wrap_pyfunction!(py_set_local_timezone, m)?)?;

    Ok(())
}
