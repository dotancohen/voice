//! Search functionality for Voice.
//!
//! This module provides search parsing and execution logic.
//! It is used by both the GUI and CLI interfaces.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use serde::{Deserialize, Serialize};

use crate::database::{Database, NoteRow};
use crate::error::VoiceResult;

/// Parsed search input.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParsedSearch {
    /// List of tag search terms (without 'tag:' prefix)
    pub tag_terms: Vec<String>,
    /// Free text search query
    pub free_text: String,
}

impl ParsedSearch {
    /// Create an empty parsed search
    pub fn empty() -> Self {
        Self {
            tag_terms: Vec::new(),
            free_text: String::new(),
        }
    }

    /// Check if search has any criteria
    pub fn is_empty(&self) -> bool {
        self.tag_terms.is_empty() && self.free_text.is_empty()
    }
}

/// Result of a search operation.
#[derive(Debug, Clone)]
pub struct SearchResult {
    /// List of matching note dictionaries
    pub notes: Vec<NoteRow>,
    /// List of tag terms that matched multiple tags
    pub ambiguous_tags: Vec<String>,
    /// List of tag terms that matched no tags
    pub not_found_tags: Vec<String>,
}

/// Parse search input to extract tag: keywords and free text.
///
/// Supports:
/// - tag:tagname for simple tag searches
/// - tag:Parent/Child/Grandchild for hierarchical paths
/// - Free text for content search
/// - Multiple tags combined with AND logic
///
/// # Arguments
/// * `search_input` - Raw search input string
///
/// # Returns
/// ParsedSearch with extracted tag terms and free text.
pub fn parse_search_input(search_input: &str) -> ParsedSearch {
    if search_input.trim().is_empty() {
        return ParsedSearch::empty();
    }

    let words = search_input.split_whitespace();
    let mut tag_terms = Vec::new();
    let mut text_words = Vec::new();

    for word in words {
        if word.to_lowercase().starts_with("tag:") {
            // Extract tag name/path (everything after "tag:")
            let tag_name = &word[4..];
            if !tag_name.is_empty() {
                tag_terms.push(tag_name.to_string());
            }
        } else {
            text_words.push(word.to_string());
        }
    }

    ParsedSearch {
        tag_terms,
        free_text: text_words.join(" "),
    }
}

/// Get the full hierarchical path for a tag.
///
/// Traverses up the tag hierarchy to build the complete path.
pub fn get_tag_full_path(db: &Database, tag_id: &str) -> VoiceResult<String> {
    let mut path_parts = Vec::new();
    let mut current_id = Some(tag_id.to_string());

    while let Some(ref id) = current_id {
        match db.get_tag(id)? {
            Some(tag) => {
                path_parts.insert(0, tag.name.clone());
                current_id = tag.parent_id;
            }
            None => break,
        }
    }

    Ok(path_parts.join("/"))
}

/// Resolve a tag search term to tag IDs.
///
/// Handles both simple tag names and hierarchical paths.
/// For ambiguous tags (same name in different locations), returns all matches.
///
/// # Returns
/// Tuple of:
/// - List of tag IDs (including descendants) matching the term
/// - Boolean indicating if the term was ambiguous (matched multiple tags)
/// - Boolean indicating if the term was not found
pub fn resolve_tag_term(db: &Database, tag_term: &str) -> VoiceResult<(Vec<String>, bool, bool)> {
    // Get all tags matching this path
    let matching_tags = db.get_all_tags_by_path(tag_term)?;

    if matching_tags.is_empty() {
        return Ok((vec![], false, true)); // Not found
    }

    // Collect all descendants from all matching tags
    let mut all_descendants = Vec::new();
    for tag in &matching_tags {
        let descendants = db.get_tag_descendants(&tag.id)?;
        for desc_bytes in descendants {
            if let Ok(uuid) = uuid::Uuid::from_slice(&desc_bytes) {
                all_descendants.push(uuid.simple().to_string());
            }
        }
    }

    // Remove duplicates while preserving order
    let mut seen = std::collections::HashSet::new();
    all_descendants.retain(|x| seen.insert(x.clone()));

    let is_ambiguous = matching_tags.len() > 1;

    Ok((all_descendants, is_ambiguous, false))
}

/// Find which tag terms are ambiguous.
pub fn find_ambiguous_tags(db: &Database, tag_terms: &[String]) -> VoiceResult<Vec<String>> {
    let mut ambiguous = Vec::new();

    for term in tag_terms {
        let matching_tags = db.get_all_tags_by_path(term)?;
        if matching_tags.len() > 1 {
            ambiguous.push(format!("tag:{}", term));
        }
    }

    Ok(ambiguous)
}

/// Execute a full search operation.
///
/// Parses the search input, resolves tags, and queries the database.
pub fn execute_search(db: &Database, search_input: &str) -> VoiceResult<SearchResult> {
    let parsed = parse_search_input(search_input);

    // Resolve tag terms to ID groups
    let mut tag_id_groups: Vec<Vec<String>> = Vec::new();
    let mut ambiguous_tags: Vec<String> = Vec::new();
    let mut not_found_tags: Vec<String> = Vec::new();

    for tag_term in &parsed.tag_terms {
        let (tag_ids, is_ambiguous, not_found) = resolve_tag_term(db, tag_term)?;

        if not_found {
            not_found_tags.push(tag_term.clone());
        } else {
            tag_id_groups.push(tag_ids);

            if is_ambiguous {
                ambiguous_tags.push(format!("tag:{}", tag_term));
            }
        }
    }

    // If any tag was not found, return empty results
    if !not_found_tags.is_empty() {
        return Ok(SearchResult {
            notes: vec![],
            ambiguous_tags,
            not_found_tags,
        });
    }

    // Perform search
    let notes = if !parsed.free_text.is_empty() || !tag_id_groups.is_empty() {
        let text_query = if parsed.free_text.is_empty() {
            None
        } else {
            Some(parsed.free_text.as_str())
        };
        let tag_groups = if tag_id_groups.is_empty() {
            None
        } else {
            Some(&tag_id_groups)
        };
        db.search_notes(text_query, tag_groups)?
    } else {
        // No search criteria, return all notes
        db.get_all_notes()?
    };

    Ok(SearchResult {
        notes,
        ambiguous_tags,
        not_found_tags,
    })
}

/// Build a search term for a tag.
///
/// If use_full_path is true, always use full path.
/// Otherwise, use simple name unless the tag name is ambiguous.
pub fn build_tag_search_term(
    db: &Database,
    tag_id: &str,
    use_full_path: bool,
) -> VoiceResult<String> {
    let tag = match db.get_tag(tag_id)? {
        Some(t) => t,
        None => return Ok(String::new()),
    };

    // Check if we should use full path
    if use_full_path {
        let path = get_tag_full_path(db, tag_id)?;
        return Ok(format!("tag:{}", path));
    }

    // Check if tag name is ambiguous
    let matching_tags = db.get_tags_by_name(&tag.name)?;
    if matching_tags.len() > 1 {
        // Ambiguous - use full path
        let path = get_tag_full_path(db, tag_id)?;
        Ok(format!("tag:{}", path))
    } else {
        // Not ambiguous - use simple name
        Ok(format!("tag:{}", tag.name))
    }
}

// ============================================================================
// Python bindings
// ============================================================================

/// Python wrapper for ParsedSearch
#[pyclass(name = "ParsedSearch")]
#[derive(Clone)]
pub struct PyParsedSearch {
    inner: ParsedSearch,
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

    fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    fn __repr__(&self) -> String {
        format!(
            "ParsedSearch(tag_terms={:?}, free_text='{}')",
            self.inner.tag_terms, self.inner.free_text
        )
    }
}

/// Python wrapper for SearchResult
#[pyclass(name = "SearchResult")]
pub struct PySearchResult {
    notes: Vec<NoteRow>,
    ambiguous_tags: Vec<String>,
    not_found_tags: Vec<String>,
}

#[pymethods]
impl PySearchResult {
    #[getter]
    fn notes(&self, py: Python<'_>) -> PyResult<PyObject> {
        let list = PyList::empty(py);
        for note in &self.notes {
            let dict = PyDict::new(py);
            dict.set_item("id", &note.id)?;
            dict.set_item("created_at", &note.created_at)?;
            dict.set_item("content", &note.content)?;
            dict.set_item("modified_at", &note.modified_at)?;
            dict.set_item("deleted_at", &note.deleted_at)?;
            dict.set_item("tag_names", &note.tag_names)?;
            list.append(dict)?;
        }
        Ok(list.into())
    }

    #[getter]
    fn ambiguous_tags(&self) -> Vec<String> {
        self.ambiguous_tags.clone()
    }

    #[getter]
    fn not_found_tags(&self) -> Vec<String> {
        self.not_found_tags.clone()
    }

    fn __repr__(&self) -> String {
        format!(
            "SearchResult(notes={}, ambiguous_tags={:?}, not_found_tags={:?})",
            self.notes.len(),
            self.ambiguous_tags,
            self.not_found_tags
        )
    }
}

/// Parse search input
#[pyfunction]
#[pyo3(name = "parse_search_input")]
pub fn py_parse_search_input(search_input: &str) -> PyParsedSearch {
    PyParsedSearch {
        inner: parse_search_input(search_input),
    }
}

/// Execute search
#[pyfunction]
#[pyo3(name = "execute_search")]
pub fn py_execute_search(
    db: &crate::database::PyDatabase,
    search_input: &str,
) -> PyResult<PySearchResult> {
    // Note: This requires access to the internal database
    // For now, we'll need to refactor PyDatabase to expose execution
    // This is a placeholder that will be implemented when integrating
    Err(pyo3::exceptions::PyNotImplementedError::new_err(
        "execute_search requires database access - use Database.search_notes instead",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_empty() {
        let result = parse_search_input("");
        assert!(result.is_empty());
        assert!(result.tag_terms.is_empty());
        assert!(result.free_text.is_empty());
    }

    #[test]
    fn test_parse_free_text_only() {
        let result = parse_search_input("hello world");
        assert_eq!(result.free_text, "hello world");
        assert!(result.tag_terms.is_empty());
    }

    #[test]
    fn test_parse_tag_only() {
        let result = parse_search_input("tag:Work");
        assert_eq!(result.tag_terms, vec!["Work"]);
        assert!(result.free_text.is_empty());
    }

    #[test]
    fn test_parse_mixed() {
        let result = parse_search_input("hello tag:Work world tag:Important");
        assert_eq!(result.tag_terms, vec!["Work", "Important"]);
        assert_eq!(result.free_text, "hello world");
    }

    #[test]
    fn test_parse_tag_path() {
        let result = parse_search_input("tag:Europe/France/Paris");
        assert_eq!(result.tag_terms, vec!["Europe/France/Paris"]);
    }

    #[test]
    fn test_parse_case_insensitive() {
        let result = parse_search_input("TAG:Work Tag:Home");
        assert_eq!(result.tag_terms, vec!["Work", "Home"]);
    }

    #[test]
    fn test_parse_whitespace() {
        let result = parse_search_input("  hello   tag:Work   world  ");
        assert_eq!(result.tag_terms, vec!["Work"]);
        assert_eq!(result.free_text, "hello world");
    }
}
