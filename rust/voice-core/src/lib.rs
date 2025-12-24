//! Voice Core - Rust implementation of the Voice note-taking application core.
//!
//! This library provides the core functionality for Voice:
//! - Data models (Note, Tag, NoteTag)
//! - Database operations (SQLite)
//! - Sync protocol (client and server)
//! - Conflict resolution
//! - Configuration management
//!
//! The library is designed to be called from Python via PyO3 bindings,
//! enabling the existing Python UI (Qt, Textual, CLI) to use Rust for
//! all business logic.

pub mod config;
pub mod conflicts;
pub mod database;
pub mod error;
pub mod merge;
pub mod models;
pub mod search;
pub mod sync_client;
pub mod sync_server;
pub mod tls;
pub mod validation;

// Re-export commonly used types
pub use config::Config;
pub use database::Database;
pub use error::{VoiceError, VoiceResult};
pub use models::{Note, NoteTag, Tag};
pub use error::ValidationError;

use pyo3::prelude::*;

/// Python module for voice_core
#[pymodule]
fn voice_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Register error types
    m.add("ValidationError", m.py().get_type::<error::PyValidationError>())?;
    m.add("DatabaseError", m.py().get_type::<error::PyDatabaseError>())?;
    m.add("SyncError", m.py().get_type::<error::PySyncError>())?;

    // Register model classes
    m.add_class::<models::PyNote>()?;
    m.add_class::<models::PyTag>()?;
    m.add_class::<models::PyNoteTag>()?;

    // Register database class
    m.add_class::<database::PyDatabase>()?;

    // Register config class
    m.add_class::<config::PyConfig>()?;

    // Register search functions
    m.add_class::<search::PySearchResult>()?;
    m.add_class::<search::PyParsedSearch>()?;
    m.add_function(wrap_pyfunction!(search::py_parse_search_input, m)?)?;
    m.add_function(wrap_pyfunction!(search::py_execute_search, m)?)?;

    // Register merge functions
    m.add_class::<merge::PyMergeResult>()?;
    m.add_function(wrap_pyfunction!(merge::py_merge_content, m)?)?;

    // Register conflict manager
    m.add_class::<conflicts::PyConflictManager>()?;
    m.add_class::<conflicts::PyNoteContentConflict>()?;
    m.add_class::<conflicts::PyNoteDeleteConflict>()?;
    m.add_class::<conflicts::PyTagRenameConflict>()?;

    // Register sync client
    m.add_class::<sync_client::PySyncClient>()?;
    m.add_class::<sync_client::PySyncResult>()?;

    // Register validation functions
    m.add_function(wrap_pyfunction!(validation::py_validate_uuid_hex, m)?)?;
    m.add_function(wrap_pyfunction!(validation::py_uuid_to_hex, m)?)?;
    m.add_function(wrap_pyfunction!(validation::py_validate_note_id, m)?)?;
    m.add_function(wrap_pyfunction!(validation::py_validate_tag_id, m)?)?;
    m.add_function(wrap_pyfunction!(validation::py_validate_tag_name, m)?)?;
    m.add_function(wrap_pyfunction!(validation::py_validate_note_content, m)?)?;
    m.add_function(wrap_pyfunction!(validation::py_validate_search_query, m)?)?;

    // Register sync server functions
    m.add_function(wrap_pyfunction!(sync_server::py_start_sync_server, m)?)?;
    m.add_function(wrap_pyfunction!(sync_server::py_stop_sync_server, m)?)?;

    // Register database helper function
    m.add_function(wrap_pyfunction!(database::py_set_local_device_id, m)?)?;

    Ok(())
}
