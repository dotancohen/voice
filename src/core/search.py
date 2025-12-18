"""Search functionality for Voice Rewrite.

This module provides search parsing and execution logic.
It is used by both the GUI and CLI interfaces.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.database import Database

logger = logging.getLogger(__name__)


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

    Supports:
    - tag:tagname for simple tag searches
    - tag:Parent/Child/Grandchild for hierarchical paths
    - Free text for content search
    - Multiple tags combined with AND logic

    Args:
        search_input: Raw search input string

    Returns:
        ParsedSearch with extracted tag terms and free text.

    Examples:
        >>> parse_search_input("hello tag:Work world")
        ParsedSearch(tag_terms=['Work'], free_text='hello world')

        >>> parse_search_input("tag:Europe/France meeting")
        ParsedSearch(tag_terms=['Europe/France'], free_text='meeting')
    """
    if not search_input or not search_input.strip():
        return ParsedSearch(tag_terms=[], free_text="")

    words = search_input.split()
    tag_terms: List[str] = []
    text_words: List[str] = []

    for word in words:
        if word.lower().startswith("tag:"):
            # Extract tag name/path (everything after "tag:")
            tag_name = word[4:]  # Remove "tag:" prefix
            if tag_name:
                tag_terms.append(tag_name)
        else:
            text_words.append(word)

    free_text = " ".join(text_words).strip()

    return ParsedSearch(tag_terms=tag_terms, free_text=free_text)


def get_tag_full_path(db: Database, tag_id: int) -> str:
    """Get the full hierarchical path for a tag.

    Traverses up the tag hierarchy to build the complete path.

    Args:
        db: Database connection
        tag_id: Tag ID to get path for

    Returns:
        Full path like "Europe/France/Paris" or just "Work" for root tags.
        Returns empty string if tag not found.
    """
    path_parts: List[str] = []
    current_id: Optional[int] = tag_id

    while current_id is not None:
        tag = db.get_tag(current_id)
        if not tag:
            break
        path_parts.insert(0, tag["name"])
        current_id = tag.get("parent_id")

    return "/".join(path_parts)


def resolve_tag_term(
    db: Database, tag_term: str
) -> Tuple[List[int], bool, bool]:
    """Resolve a tag search term to tag IDs.

    Handles both simple tag names and hierarchical paths.
    For ambiguous tags (same name in different locations), returns all matches.

    Args:
        db: Database connection
        tag_term: Tag name or path (e.g., "Work" or "Europe/France/Paris")

    Returns:
        Tuple of:
        - List of tag IDs (including descendants) matching the term
        - Boolean indicating if the term was ambiguous (matched multiple tags)
        - Boolean indicating if the term was not found
    """
    # Get all tags matching this path
    matching_tags = db.get_all_tags_by_path(tag_term)

    if not matching_tags:
        return ([], False, True)  # Not found

    # Collect all descendants from all matching tags
    all_descendants: List[int] = []
    for tag in matching_tags:
        descendants = db.get_tag_descendants(tag["id"])
        all_descendants.extend(descendants)

    # Remove duplicates while preserving some order
    all_descendants = list(dict.fromkeys(all_descendants))

    is_ambiguous = len(matching_tags) > 1

    return (all_descendants, is_ambiguous, False)


def find_ambiguous_tags(db: Database, tag_terms: List[str]) -> List[str]:
    """Find which tag terms are ambiguous.

    Args:
        db: Database connection
        tag_terms: List of tag search terms

    Returns:
        List of tag terms that match multiple tags (formatted as "tag:term")
    """
    ambiguous: List[str] = []

    for term in tag_terms:
        matching_tags = db.get_all_tags_by_path(term)
        if len(matching_tags) > 1:
            ambiguous.append(f"tag:{term}")

    return ambiguous


def execute_search(db: Database, search_input: str) -> SearchResult:
    """Execute a full search operation.

    Parses the search input, resolves tags, and queries the database.

    Args:
        db: Database connection
        search_input: Raw search input string

    Returns:
        SearchResult containing matching notes and metadata about the search.
    """
    parsed = parse_search_input(search_input)

    # Resolve tag terms to ID groups
    tag_id_groups: List[List[int]] = []
    ambiguous_tags: List[str] = []
    not_found_tags: List[str] = []

    for tag_term in parsed.tag_terms:
        tag_ids, is_ambiguous, not_found = resolve_tag_term(db, tag_term)

        if not_found:
            not_found_tags.append(tag_term)
            logger.warning(f"Tag path '{tag_term}' not found")
        else:
            tag_id_groups.append(tag_ids)

            if is_ambiguous:
                ambiguous_tags.append(f"tag:{tag_term}")
                logger.info(
                    f"Tag '{tag_term}' is ambiguous - matched multiple tags, "
                    f"total {len(tag_ids)} tag IDs with descendants (OR logic)"
                )
            else:
                logger.info(
                    f"Tag '{tag_term}' matched {len(tag_ids)} tags (including descendants)"
                )

    # If any tag was not found, return empty results
    if not_found_tags:
        return SearchResult(
            notes=[],
            ambiguous_tags=ambiguous_tags,
            not_found_tags=not_found_tags,
        )

    # Perform search
    if parsed.free_text or tag_id_groups:
        notes = db.search_notes(
            text_query=parsed.free_text if parsed.free_text else None,
            tag_id_groups=tag_id_groups if tag_id_groups else None,
        )
    else:
        # No search criteria, return all notes
        notes = db.get_all_notes()

    logger.info(f"Search returned {len(notes)} notes")

    return SearchResult(
        notes=notes,
        ambiguous_tags=ambiguous_tags,
        not_found_tags=not_found_tags,
    )


def build_tag_search_term(db: Database, tag_id: int, use_full_path: bool = False) -> str:
    """Build a search term for a tag.

    Args:
        db: Database connection
        tag_id: Tag ID to build term for
        use_full_path: If True, always use full path. If False, use simple name
                       unless the tag name is ambiguous.

    Returns:
        Search term like "tag:Work" or "tag:Europe/France/Paris"
    """
    tag = db.get_tag(tag_id)
    if not tag:
        return ""

    tag_name = tag["name"]

    # Check if we should use full path
    if use_full_path:
        path = get_tag_full_path(db, tag_id)
        return f"tag:{path}"

    # Check if tag name is ambiguous
    matching_tags = db.get_tags_by_name(tag_name)
    if len(matching_tags) > 1:
        # Ambiguous - use full path
        path = get_tag_full_path(db, tag_id)
        return f"tag:{path}"
    else:
        # Not ambiguous - use simple name
        return f"tag:{tag_name}"
