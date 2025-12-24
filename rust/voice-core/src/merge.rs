//! Merge utilities for conflict resolution.
//!
//! Uses diff algorithm to combine changes from two sources,
//! producing conflict markers when content differs.
//! This ensures no data loss during synchronization.

use pyo3::prelude::*;
use similar::{ChangeTag, TextDiff};

/// Result of a merge operation.
#[derive(Debug, Clone)]
pub struct MergeResult {
    /// The merged content (may contain conflict markers if conflicted)
    pub content: String,
    /// True if the merge produced conflicts
    pub has_conflicts: bool,
    /// Number of conflict regions in the merge
    pub conflict_count: usize,
}

impl MergeResult {
    /// Create a non-conflicted merge result
    pub fn clean(content: String) -> Self {
        Self {
            content,
            has_conflicts: false,
            conflict_count: 0,
        }
    }

    /// Create a conflicted merge result
    pub fn conflicted(content: String, conflict_count: usize) -> Self {
        Self {
            content,
            has_conflicts: conflict_count > 0,
            conflict_count,
        }
    }
}

/// Merge two versions of text content.
///
/// Compares local and remote line-by-line. Lines that match are kept as-is.
/// Lines that differ get wrapped in conflict markers to preserve both versions.
///
/// # Arguments
/// * `local` - The local version (current device's content)
/// * `remote` - The remote version (other device's content)
/// * `local_label` - Label for local version in conflict markers
/// * `remote_label` - Label for remote version in conflict markers
///
/// # Returns
/// MergeResult with merged content and conflict status
pub fn merge_content(
    local: &str,
    remote: &str,
    local_label: &str,
    remote_label: &str,
) -> MergeResult {
    // If content is identical, no merge needed
    if local == remote {
        return MergeResult::clean(local.to_string());
    }

    // Use similar crate to do line-by-line diff
    let diff = TextDiff::from_lines(local, remote);

    let mut merged = String::new();
    let mut conflict_count = 0;
    let mut in_local_only: Vec<String> = Vec::new();
    let mut in_remote_only: Vec<String> = Vec::new();

    for change in diff.iter_all_changes() {
        match change.tag() {
            ChangeTag::Equal => {
                // Flush any pending conflicts
                if !in_local_only.is_empty() || !in_remote_only.is_empty() {
                    conflict_count += 1;
                    merged.push_str(&format!("<<<<<<< {}\n", local_label));
                    for line in &in_local_only {
                        merged.push_str(line);
                    }
                    merged.push_str("=======\n");
                    for line in &in_remote_only {
                        merged.push_str(line);
                    }
                    merged.push_str(&format!(">>>>>>> {}\n", remote_label));
                    in_local_only.clear();
                    in_remote_only.clear();
                }
                merged.push_str(change.value());
            }
            ChangeTag::Delete => {
                // Line only in local
                in_local_only.push(change.value().to_string());
            }
            ChangeTag::Insert => {
                // Line only in remote
                in_remote_only.push(change.value().to_string());
            }
        }
    }

    // Flush any remaining conflicts
    if !in_local_only.is_empty() || !in_remote_only.is_empty() {
        conflict_count += 1;
        merged.push_str(&format!("<<<<<<< {}\n", local_label));
        for line in &in_local_only {
            merged.push_str(line);
        }
        merged.push_str("=======\n");
        for line in &in_remote_only {
            merged.push_str(line);
        }
        merged.push_str(&format!(">>>>>>> {}\n", remote_label));
    }

    MergeResult::conflicted(merged, conflict_count)
}

/// Perform a 3-way merge of text content.
///
/// If both local and remote made the same changes, they're accepted.
/// If they made different changes to the same region, conflict markers are added.
///
/// # Arguments
/// * `base` - Original content (common ancestor)
/// * `local` - Local version
/// * `remote` - Remote version
///
/// # Returns
/// MergeResult with merged content and conflict info
pub fn diff3_merge(base: &str, local: &str, remote: &str) -> MergeResult {
    // If no base, use simple merge
    if base.is_empty() {
        return merge_content(local, remote, "LOCAL", "REMOTE");
    }

    // If local unchanged from base, take remote
    if local == base {
        return MergeResult::clean(remote.to_string());
    }

    // If remote unchanged from base, take local
    if remote == base {
        return MergeResult::clean(local.to_string());
    }

    // If local and remote are the same, no conflict
    if local == remote {
        return MergeResult::clean(local.to_string());
    }

    // Both changed - need to do actual 3-way merge
    // For now, use simple merge with conflict markers
    merge_content(local, remote, "LOCAL", "REMOTE")
}

/// Attempt automatic merge if possible.
///
/// Returns merged content if successful, None if conflicts exist.
pub fn auto_merge_if_possible(
    local_content: &str,
    remote_content: &str,
    base_content: Option<&str>,
) -> Option<String> {
    if local_content == remote_content {
        return Some(local_content.to_string());
    }

    if let Some(base) = base_content {
        let result = diff3_merge(base, local_content, remote_content);
        if !result.has_conflicts {
            return Some(result.content);
        }
    }

    None
}

/// Get a human-readable diff between two versions.
pub fn get_diff_preview(local: &str, remote: &str) -> String {
    let diff = TextDiff::from_lines(local, remote);

    let mut output = String::new();
    output.push_str("--- Local\n");
    output.push_str("+++ Remote\n");

    for change in diff.iter_all_changes() {
        let sign = match change.tag() {
            ChangeTag::Delete => "-",
            ChangeTag::Insert => "+",
            ChangeTag::Equal => " ",
        };
        output.push_str(sign);
        output.push_str(change.value());
    }

    output
}

// ============================================================================
// Python bindings
// ============================================================================

/// Python wrapper for MergeResult
#[pyclass(name = "MergeResult")]
#[derive(Clone)]
pub struct PyMergeResult {
    inner: MergeResult,
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

    fn __repr__(&self) -> String {
        format!(
            "MergeResult(has_conflicts={}, conflict_count={})",
            self.inner.has_conflicts, self.inner.conflict_count
        )
    }
}

/// Merge two versions of text content
#[pyfunction]
#[pyo3(name = "merge_content")]
#[pyo3(signature = (local, remote, local_label="LOCAL", remote_label="REMOTE"))]
pub fn py_merge_content(
    local: &str,
    remote: &str,
    local_label: &str,
    remote_label: &str,
) -> PyMergeResult {
    let result = merge_content(local, remote, local_label, remote_label);
    PyMergeResult { inner: result }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_identical_content() {
        let result = merge_content("same", "same", "LOCAL", "REMOTE");
        assert!(!result.has_conflicts);
        assert_eq!(result.conflict_count, 0);
        assert_eq!(result.content, "same");
    }

    #[test]
    fn test_different_content() {
        let result = merge_content("local version\n", "remote version\n", "LOCAL", "REMOTE");
        assert!(result.has_conflicts);
        assert_eq!(result.conflict_count, 1);
        assert!(result.content.contains("<<<<<<< LOCAL"));
        assert!(result.content.contains("======="));
        assert!(result.content.contains(">>>>>>> REMOTE"));
    }

    #[test]
    fn test_multiline_merge() {
        let local = "line 1\nlocal line 2\nline 3\n";
        let remote = "line 1\nremote line 2\nline 3\n";
        let result = merge_content(local, remote, "LOCAL", "REMOTE");

        assert!(result.has_conflicts);
        assert!(result.content.contains("line 1\n"));
        assert!(result.content.contains("line 3\n"));
    }

    #[test]
    fn test_diff3_no_base() {
        let result = diff3_merge("", "local", "remote");
        assert!(result.has_conflicts);
    }

    #[test]
    fn test_diff3_local_unchanged() {
        let result = diff3_merge("base content", "base content", "remote content");
        assert!(!result.has_conflicts);
        assert_eq!(result.content, "remote content");
    }

    #[test]
    fn test_diff3_remote_unchanged() {
        let result = diff3_merge("base content", "local content", "base content");
        assert!(!result.has_conflicts);
        assert_eq!(result.content, "local content");
    }

    #[test]
    fn test_diff3_same_changes() {
        let result = diff3_merge("base", "same change", "same change");
        assert!(!result.has_conflicts);
        assert_eq!(result.content, "same change");
    }

    #[test]
    fn test_auto_merge_identical() {
        let result = auto_merge_if_possible("same", "same", None);
        assert_eq!(result, Some("same".to_string()));
    }

    #[test]
    fn test_auto_merge_with_conflicts() {
        let result = auto_merge_if_possible("local", "remote", None);
        assert!(result.is_none());
    }

    #[test]
    fn test_get_diff_preview() {
        let preview = get_diff_preview("line 1\nline 2\n", "line 1\nline 2 modified\n");
        assert!(preview.contains("--- Local"));
        assert!(preview.contains("+++ Remote"));
    }
}
