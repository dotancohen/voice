"""Search functionality for Voice.

This module provides search parsing and execution logic.
It is used by both the GUI and CLI interfaces.

This is a wrapper around the Rust voicecore extension.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Import from Rust extension
from voicecore import (
    ParsedSearch as RustParsedSearch,
    SearchResult as RustSearchResult,
    parse_search_input as _rust_parse_search_input,
    execute_search as _rust_execute_search,
    resolve_tag_term as _rust_resolve_tag_term,
    get_tag_full_path as _rust_get_tag_full_path,
    find_ambiguous_tags as _rust_find_ambiguous_tags,
    build_tag_search_term as _rust_build_tag_search_term,
)

from .database import Database

logger = logging.getLogger(__name__)

__all__ = [
    "SearchResult",
    "ParsedSearch",
    "parse_search_input",
    "get_tag_full_path",
    "resolve_tag_term",
    "find_ambiguous_tags",
    "execute_search",
    "build_tag_search_term",
]


@dataclass
class SearchResult:
    """Result of a search operation.

    Attributes:
        notes: List of matching note dictionaries
        ambiguous_tags: List of tag terms that matched multiple tags
        not_found_tags: List of tag terms that matched no tags
    """

    notes: List[Dict[str, Any]]
    ambiguous_tags: List[str]
    not_found_tags: List[str]


@dataclass
class ParsedSearch:
    """Parsed search input.

    Attributes:
        tag_terms: List of tag search terms (without 'tag:' prefix)
        free_text: Free text search query
    """

    tag_terms: List[str]
    free_text: str


def parse_search_input(search_input: str) -> ParsedSearch:
    """Parse search input to extract tag: keywords and free text.

    Uses the Rust implementation for parsing.

    Args:
        search_input: Raw search input string

    Returns:
        ParsedSearch with extracted tag terms and free text.
    """
    if not search_input or not search_input.strip():
        return ParsedSearch(tag_terms=[], free_text="")

    rust_result = _rust_parse_search_input(search_input)
    return ParsedSearch(
        tag_terms=list(rust_result.tag_terms),
        free_text=rust_result.free_text,
    )


def get_tag_full_path(db: Database, tag_id: str) -> str:
    """Get the full hierarchical path for a tag.

    This is a thin wrapper around the Rust implementation.

    Args:
        db: Database connection
        tag_id: Tag ID (hex string) to get path for

    Returns:
        Full path like "Europe/France/Paris" or just "Work" for root tags.
    """
    return _rust_get_tag_full_path(db._rust_db, tag_id)


def resolve_tag_term(
    db: Database, tag_term: str
) -> Tuple[List[str], bool, bool]:
    """Resolve a tag search term to tag IDs.

    This is a thin wrapper around the Rust implementation.

    Args:
        db: Database connection
        tag_term: Tag name or path (e.g., "Work" or "Europe/France/Paris")

    Returns:
        Tuple of:
        - List of tag IDs (hex strings, including descendants) matching the term
        - Boolean indicating if the term was ambiguous (matched multiple tags)
        - Boolean indicating if the term was not found
    """
    return _rust_resolve_tag_term(db._rust_db, tag_term)


def find_ambiguous_tags(db: Database, tag_terms: List[str]) -> List[str]:
    """Find which tag terms are ambiguous.

    This is a thin wrapper around the Rust implementation.

    Args:
        db: Database connection
        tag_terms: List of tag search terms

    Returns:
        List of tag terms that match multiple tags (formatted as "tag:term")
    """
    return _rust_find_ambiguous_tags(db._rust_db, tag_terms)


def execute_search(db: Database, search_input: str) -> SearchResult:
    """Execute a full search operation.

    Parses the search input, resolves tags, and queries the database.
    This is a thin wrapper around the Rust implementation.

    Args:
        db: Database connection
        search_input: Raw search input string

    Returns:
        SearchResult containing matching notes and metadata about the search.
    """
    # Call Rust implementation
    rust_result = _rust_execute_search(db._rust_db, search_input)

    logger.info(f"Search returned {len(rust_result.notes)} notes")
    if rust_result.ambiguous_tags:
        logger.info(f"Ambiguous tags: {rust_result.ambiguous_tags}")
    if rust_result.not_found_tags:
        logger.info(f"Tags not found: {rust_result.not_found_tags}")

    return SearchResult(
        notes=rust_result.notes,
        ambiguous_tags=rust_result.ambiguous_tags,
        not_found_tags=rust_result.not_found_tags,
    )


def build_tag_search_term(db: Database, tag_id: str, use_full_path: bool = False) -> str:
    """Build a search term for a tag.

    This is a thin wrapper around the Rust implementation.

    Args:
        db: Database connection
        tag_id: Tag ID (hex string) to build term for
        use_full_path: If True, always use full path. If False, use simple name
                       unless the tag name is ambiguous.

    Returns:
        Search term like "tag:Work" or "tag:Europe/France/Paris"
    """
    return _rust_build_tag_search_term(db._rust_db, tag_id, use_full_path)
