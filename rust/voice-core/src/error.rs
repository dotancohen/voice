//! Error types for Voice Core.
//!
//! This module defines all error types used throughout the library,
//! with Python exception mappings for PyO3 integration.

use pyo3::exceptions::{PyException, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::create_exception;
use thiserror::Error;

/// Result type alias for Voice operations
pub type VoiceResult<T> = Result<T, VoiceError>;

/// Main error type for Voice operations
#[derive(Error, Debug)]
pub enum VoiceError {
    #[error("Validation error in {field}: {message}")]
    Validation { field: String, message: String },

    #[error("Database error: {0}")]
    Database(#[from] rusqlite::Error),

    #[error("Database operation failed: {0}")]
    DatabaseOperation(String),

    #[error("Sync error: {0}")]
    Sync(String),

    #[error("Network error: {0}")]
    Network(String),

    #[error("TLS error: {0}")]
    Tls(String),

    #[error("Configuration error: {0}")]
    Config(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("UUID error: {0}")]
    Uuid(#[from] uuid::Error),

    #[error("Not found: {0}")]
    NotFound(String),

    #[error("Conflict: {0}")]
    Conflict(String),

    #[error("{0}")]
    Other(String),
}

impl VoiceError {
    /// Create a new validation error
    pub fn validation(field: impl Into<String>, message: impl Into<String>) -> Self {
        VoiceError::Validation {
            field: field.into(),
            message: message.into(),
        }
    }

    /// Create a new sync error
    pub fn sync(message: impl Into<String>) -> Self {
        VoiceError::Sync(message.into())
    }

    /// Create a new database operation error
    pub fn database_op(message: impl Into<String>) -> Self {
        VoiceError::DatabaseOperation(message.into())
    }
}

// Python exception types - using create_exception! macro for proper exception inheritance
create_exception!(voice_core, PyValidationError, PyValueError, "Validation error with field and message attributes.");
create_exception!(voice_core, PyDatabaseError, PyException);
create_exception!(voice_core, PySyncError, PyException);
create_exception!(voice_core, PyConfigError, PyException);
create_exception!(voice_core, PyTlsError, PyException);

impl From<VoiceError> for PyErr {
    fn from(err: VoiceError) -> PyErr {
        match err {
            VoiceError::Validation { field, message } => {
                // Store field and message in the exception args for extraction
                let err_msg = format!("{}:{}", field, message);
                PyValidationError::new_err(err_msg)
            }
            VoiceError::Database(e) => PyDatabaseError::new_err(e.to_string()),
            VoiceError::DatabaseOperation(msg) => PyDatabaseError::new_err(msg),
            VoiceError::Sync(msg) => PySyncError::new_err(msg),
            VoiceError::Network(msg) => PySyncError::new_err(format!("Network: {}", msg)),
            VoiceError::Tls(msg) => PyTlsError::new_err(msg),
            VoiceError::Config(msg) => PyConfigError::new_err(msg),
            VoiceError::Io(e) => PyRuntimeError::new_err(e.to_string()),
            VoiceError::Json(e) => PyValueError::new_err(e.to_string()),
            VoiceError::Uuid(e) => PyValidationError::new_err(format!("uuid:{}", e)),
            VoiceError::NotFound(msg) => PyValueError::new_err(format!("Not found: {}", msg)),
            VoiceError::Conflict(msg) => PyRuntimeError::new_err(format!("Conflict: {}", msg)),
            VoiceError::Other(msg) => PyRuntimeError::new_err(msg),
        }
    }
}

/// Validation error with field and message
#[derive(Debug, Clone)]
pub struct ValidationError {
    pub field: String,
    pub message: String,
}

impl ValidationError {
    pub fn new(field: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            field: field.into(),
            message: message.into(),
        }
    }
}

impl std::fmt::Display for ValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.field, self.message)
    }
}

impl std::error::Error for ValidationError {}

impl From<ValidationError> for VoiceError {
    fn from(err: ValidationError) -> Self {
        VoiceError::Validation {
            field: err.field,
            message: err.message,
        }
    }
}

impl From<ValidationError> for PyErr {
    fn from(err: ValidationError) -> PyErr {
        PyValidationError::new_err(format!("{}: {}", err.field, err.message))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validation_error_display() {
        let err = ValidationError::new("test_field", "test message");
        assert_eq!(err.to_string(), "test_field: test message");
    }

    #[test]
    fn test_voice_error_validation() {
        let err = VoiceError::validation("field", "message");
        assert!(matches!(err, VoiceError::Validation { .. }));
    }
}
