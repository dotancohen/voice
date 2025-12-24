//! Input validation for Voice.
//!
//! This module provides validation functions for all user inputs.
//! All validators return VoiceError::Validation on failure.

use pyo3::prelude::*;
use uuid::Uuid;

use crate::error::{ValidationError, VoiceError, VoiceResult};

// Limits (matching Python implementation)
pub const MAX_TAG_NAME_LENGTH: usize = 100;
pub const MAX_NOTE_CONTENT_LENGTH: usize = 100_000; // 100KB of text
pub const MAX_SEARCH_QUERY_LENGTH: usize = 500;
pub const MAX_TAG_PATH_LENGTH: usize = 500;
pub const MAX_TAG_PATH_DEPTH: usize = 50;
pub const UUID_BYTES_LENGTH: usize = 16;

/// Validate a UUID value (must be 16 bytes).
pub fn validate_uuid(value: &[u8], field_name: &str) -> VoiceResult<()> {
    if value.len() != UUID_BYTES_LENGTH {
        return Err(VoiceError::validation(
            field_name,
            format!(
                "must be {} bytes, got {}",
                UUID_BYTES_LENGTH,
                value.len()
            ),
        ));
    }
    Ok(())
}

/// Validate and convert a UUID hex string to Uuid.
pub fn validate_uuid_hex(value: &str, field_name: &str) -> VoiceResult<Uuid> {
    // Accept both hyphenated and non-hyphenated formats
    let cleaned = value.replace('-', "");
    Uuid::parse_str(&cleaned).map_err(|e| {
        VoiceError::validation(field_name, format!("invalid UUID format: {}", e))
    })
}

/// Convert UUID to hex string (32 chars, no hyphens).
pub fn uuid_to_hex(value: &Uuid) -> String {
    value.simple().to_string()
}

/// Convert UUID bytes to hex string.
pub fn uuid_bytes_to_hex(bytes: &[u8]) -> VoiceResult<String> {
    if bytes.len() != UUID_BYTES_LENGTH {
        return Err(VoiceError::validation(
            "uuid",
            format!("must be {} bytes", UUID_BYTES_LENGTH),
        ));
    }
    let uuid = Uuid::from_slice(bytes)
        .map_err(|e| VoiceError::validation("uuid", format!("invalid UUID bytes: {}", e)))?;
    Ok(uuid.simple().to_string())
}

/// Validate a UUID entity ID (note, tag, device, etc.).
/// Accepts either bytes or hex string.
pub fn validate_entity_id(entity_id: &str, field_name: &str) -> VoiceResult<Uuid> {
    validate_uuid_hex(entity_id, field_name)
}

/// Validate a note ID.
pub fn validate_note_id(note_id: &str) -> VoiceResult<Uuid> {
    validate_entity_id(note_id, "note_id")
}

/// Validate a tag ID.
pub fn validate_tag_id(tag_id: &str) -> VoiceResult<Uuid> {
    validate_entity_id(tag_id, "tag_id")
}

/// Validate a device ID.
pub fn validate_device_id(device_id: &str) -> VoiceResult<Uuid> {
    validate_entity_id(device_id, "device_id")
}

/// Validate a list of tag IDs.
pub fn validate_tag_ids(tag_ids: &[String]) -> VoiceResult<Vec<Uuid>> {
    tag_ids
        .iter()
        .enumerate()
        .map(|(i, tag_id)| {
            validate_tag_id(tag_id).map_err(|_| {
                VoiceError::validation("tag_ids", format!("item {}: invalid tag ID", i))
            })
        })
        .collect()
}

/// Validate a tag name.
///
/// Tag names must be:
/// - Non-empty after stripping whitespace
/// - No longer than MAX_TAG_NAME_LENGTH characters
/// - Not contain path separator (/)
/// - Not be only whitespace
pub fn validate_tag_name(name: &str) -> VoiceResult<()> {
    let stripped = name.trim();

    if stripped.is_empty() {
        return Err(VoiceError::validation(
            "tag_name",
            "cannot be empty or whitespace only",
        ));
    }

    if stripped.len() > MAX_TAG_NAME_LENGTH {
        return Err(VoiceError::validation(
            "tag_name",
            format!(
                "cannot exceed {} characters (got {})",
                MAX_TAG_NAME_LENGTH,
                stripped.len()
            ),
        ));
    }

    if stripped.contains('/') {
        return Err(VoiceError::validation(
            "tag_name",
            "cannot contain '/' character (reserved for paths)",
        ));
    }

    Ok(())
}

/// Validate a tag path.
///
/// Tag paths are slash-separated tag names like "Europe/France/Paris".
pub fn validate_tag_path(path: &str) -> VoiceResult<()> {
    let stripped = path.trim();

    if stripped.is_empty() {
        return Err(VoiceError::validation(
            "tag_path",
            "cannot be empty or whitespace only",
        ));
    }

    if stripped.len() > MAX_TAG_PATH_LENGTH {
        return Err(VoiceError::validation(
            "tag_path",
            format!(
                "cannot exceed {} characters (got {})",
                MAX_TAG_PATH_LENGTH,
                stripped.len()
            ),
        ));
    }

    let parts: Vec<&str> = stripped.split('/').collect();

    if parts.len() > MAX_TAG_PATH_DEPTH {
        return Err(VoiceError::validation(
            "tag_path",
            format!(
                "cannot exceed {} levels (got {})",
                MAX_TAG_PATH_DEPTH,
                parts.len()
            ),
        ));
    }

    // Validate each part as a tag name (but allow empty parts from leading/trailing slashes)
    let non_empty_parts: Vec<&str> = parts
        .iter()
        .map(|p| p.trim())
        .filter(|p| !p.is_empty())
        .collect();

    if non_empty_parts.is_empty() {
        return Err(VoiceError::validation(
            "tag_path",
            "must contain at least one valid tag name",
        ));
    }

    for part in non_empty_parts {
        if part.len() > MAX_TAG_NAME_LENGTH {
            return Err(VoiceError::validation(
                "tag_path",
                format!(
                    "tag name '{}...' exceeds {} characters",
                    &part[..20.min(part.len())],
                    MAX_TAG_NAME_LENGTH
                ),
            ));
        }
    }

    Ok(())
}

/// Validate note content.
///
/// Note content must be:
/// - A string
/// - Non-empty after stripping whitespace
/// - No longer than MAX_NOTE_CONTENT_LENGTH characters
pub fn validate_note_content(content: &str) -> VoiceResult<()> {
    if content.trim().is_empty() {
        return Err(VoiceError::validation(
            "content",
            "cannot be empty or whitespace only",
        ));
    }

    if content.len() > MAX_NOTE_CONTENT_LENGTH {
        return Err(VoiceError::validation(
            "content",
            format!(
                "cannot exceed {} characters (got {})",
                MAX_NOTE_CONTENT_LENGTH,
                content.len()
            ),
        ));
    }

    Ok(())
}

/// Validate a search query.
///
/// Search queries can be None/empty (meaning no text filter).
/// If provided, must not exceed MAX_SEARCH_QUERY_LENGTH.
pub fn validate_search_query(query: Option<&str>) -> VoiceResult<()> {
    if let Some(q) = query {
        if q.len() > MAX_SEARCH_QUERY_LENGTH {
            return Err(VoiceError::validation(
                "search_query",
                format!(
                    "cannot exceed {} characters (got {})",
                    MAX_SEARCH_QUERY_LENGTH,
                    q.len()
                ),
            ));
        }
    }
    Ok(())
}

/// Validate a parent tag ID for tag creation/update.
pub fn validate_parent_tag_id(
    parent_id: Option<&str>,
    tag_id: Option<&str>,
) -> VoiceResult<Option<Uuid>> {
    match parent_id {
        None => Ok(None),
        Some(pid) => {
            let parent_uuid = validate_tag_id(pid)?;

            if let Some(tid) = tag_id {
                let tag_uuid = validate_tag_id(tid)?;
                if parent_uuid == tag_uuid {
                    return Err(VoiceError::validation(
                        "parent_id",
                        "tag cannot be its own parent",
                    ));
                }
            }

            Ok(Some(parent_uuid))
        }
    }
}

/// Validate tag ID groups for search.
pub fn validate_tag_id_groups(
    tag_id_groups: Option<&Vec<Vec<String>>>,
) -> VoiceResult<Option<Vec<Vec<Uuid>>>> {
    match tag_id_groups {
        None => Ok(None),
        Some(groups) => {
            let mut result = Vec::new();
            for (i, group) in groups.iter().enumerate() {
                let mut group_result = Vec::new();
                for (j, tag_id) in group.iter().enumerate() {
                    let uuid = validate_tag_id(tag_id).map_err(|_| {
                        VoiceError::validation(
                            "tag_id_groups",
                            format!("group {}, item {}: invalid tag ID", i, j),
                        )
                    })?;
                    group_result.push(uuid);
                }
                result.push(group_result);
            }
            Ok(Some(result))
        }
    }
}

// ============================================================================
// Python bindings
// ============================================================================

/// Validate and convert a UUID hex string to bytes (returns hex string for Python)
#[pyfunction]
#[pyo3(name = "validate_uuid_hex")]
#[pyo3(signature = (value, field_name=None))]
pub fn py_validate_uuid_hex(value: &str, field_name: Option<&str>) -> PyResult<String> {
    let field = field_name.unwrap_or("id");
    let uuid = validate_uuid_hex(value, field)?;
    Ok(uuid.simple().to_string())
}

/// Convert UUID bytes to hex string
#[pyfunction]
#[pyo3(name = "uuid_to_hex")]
pub fn py_uuid_to_hex(value: &[u8]) -> PyResult<String> {
    let hex = uuid_bytes_to_hex(value)?;
    Ok(hex)
}

/// Validate a note ID
#[pyfunction]
#[pyo3(name = "validate_note_id")]
pub fn py_validate_note_id(note_id: &str) -> PyResult<String> {
    let uuid = validate_note_id(note_id)?;
    Ok(uuid.simple().to_string())
}

/// Validate a tag ID
#[pyfunction]
#[pyo3(name = "validate_tag_id")]
pub fn py_validate_tag_id(tag_id: &str) -> PyResult<String> {
    let uuid = validate_tag_id(tag_id)?;
    Ok(uuid.simple().to_string())
}

/// Validate a tag name
#[pyfunction]
#[pyo3(name = "validate_tag_name")]
pub fn py_validate_tag_name(name: &str) -> PyResult<()> {
    validate_tag_name(name)?;
    Ok(())
}

/// Validate note content
#[pyfunction]
#[pyo3(name = "validate_note_content")]
pub fn py_validate_note_content(content: &str) -> PyResult<()> {
    validate_note_content(content)?;
    Ok(())
}

/// Validate a search query
#[pyfunction]
#[pyo3(name = "validate_search_query")]
#[pyo3(signature = (query=None))]
pub fn py_validate_search_query(query: Option<&str>) -> PyResult<()> {
    validate_search_query(query)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_uuid_hex_valid() {
        let uuid = Uuid::now_v7();
        let hex = uuid.simple().to_string();
        let result = validate_uuid_hex(&hex, "test");
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), uuid);
    }

    #[test]
    fn test_validate_uuid_hex_with_hyphens() {
        let uuid = Uuid::now_v7();
        let hex_with_hyphens = uuid.to_string();
        let result = validate_uuid_hex(&hex_with_hyphens, "test");
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), uuid);
    }

    #[test]
    fn test_validate_uuid_hex_invalid() {
        let result = validate_uuid_hex("not-a-uuid", "test");
        assert!(result.is_err());
    }

    #[test]
    fn test_validate_tag_name_valid() {
        assert!(validate_tag_name("Work").is_ok());
        assert!(validate_tag_name("Personal").is_ok());
        assert!(validate_tag_name("  Trimmed  ").is_ok());
    }

    #[test]
    fn test_validate_tag_name_empty() {
        assert!(validate_tag_name("").is_err());
        assert!(validate_tag_name("   ").is_err());
    }

    #[test]
    fn test_validate_tag_name_with_slash() {
        assert!(validate_tag_name("Work/Projects").is_err());
    }

    #[test]
    fn test_validate_tag_name_too_long() {
        let long_name = "a".repeat(MAX_TAG_NAME_LENGTH + 1);
        assert!(validate_tag_name(&long_name).is_err());
    }

    #[test]
    fn test_validate_tag_path_valid() {
        assert!(validate_tag_path("Work").is_ok());
        assert!(validate_tag_path("Europe/France/Paris").is_ok());
        assert!(validate_tag_path("/Work/").is_ok());
    }

    #[test]
    fn test_validate_tag_path_empty() {
        assert!(validate_tag_path("").is_err());
        assert!(validate_tag_path("   ").is_err());
        assert!(validate_tag_path("///").is_err());
    }

    #[test]
    fn test_validate_note_content_valid() {
        assert!(validate_note_content("Hello, world!").is_ok());
        assert!(validate_note_content("  Content  ").is_ok());
    }

    #[test]
    fn test_validate_note_content_empty() {
        assert!(validate_note_content("").is_err());
        assert!(validate_note_content("   ").is_err());
    }

    #[test]
    fn test_validate_note_content_too_long() {
        let long_content = "a".repeat(MAX_NOTE_CONTENT_LENGTH + 1);
        assert!(validate_note_content(&long_content).is_err());
    }

    #[test]
    fn test_validate_search_query_none() {
        assert!(validate_search_query(None).is_ok());
    }

    #[test]
    fn test_validate_search_query_valid() {
        assert!(validate_search_query(Some("hello world")).is_ok());
    }

    #[test]
    fn test_validate_search_query_too_long() {
        let long_query = "a".repeat(MAX_SEARCH_QUERY_LENGTH + 1);
        assert!(validate_search_query(Some(&long_query)).is_err());
    }

    #[test]
    fn test_validate_parent_tag_id_none() {
        assert!(validate_parent_tag_id(None, None).is_ok());
    }

    #[test]
    fn test_validate_parent_tag_id_self_reference() {
        let uuid = Uuid::now_v7();
        let hex = uuid.simple().to_string();
        let result = validate_parent_tag_id(Some(&hex), Some(&hex));
        assert!(result.is_err());
    }
}
