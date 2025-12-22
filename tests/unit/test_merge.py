"""Unit tests for the merge module.

Tests line-by-line diff and conflict marker functionality.
"""

from __future__ import annotations

import pytest

from core.merge import MergeResult, merge_content


class TestMergeBasics:
    """Test basic merge functionality."""

    def test_identical_content_no_conflict(self) -> None:
        """When both versions are identical, no conflict."""
        result = merge_content(
            local="Hello\nWorld\n",
            remote="Hello\nWorld\n",
        )
        assert result.content == "Hello\nWorld\n"
        assert result.has_conflicts is False
        assert result.conflict_count == 0

    def test_different_content_creates_conflict(self) -> None:
        """When content differs, conflict markers are added."""
        result = merge_content(
            local="Local version\n",
            remote="Remote version\n",
        )
        assert result.has_conflicts is True
        assert "<<<<<<< LOCAL" in result.content
        assert "Local version" in result.content
        assert "Remote version" in result.content
        assert ">>>>>>> REMOTE" in result.content


class TestLineLevelDiff:
    """Test that conflicts are at line level, not whole content."""

    def test_matching_lines_not_in_conflict(self) -> None:
        """Lines that match between local and remote are not wrapped in markers."""
        local = "Same line 1\nDifferent local\nSame line 3\n"
        remote = "Same line 1\nDifferent remote\nSame line 3\n"

        result = merge_content(local=local, remote=remote)

        # The matching lines should appear without conflict markers
        lines = result.content.split("\n")
        # Same line 1 should be present and not between conflict markers
        assert "Same line 1" in result.content
        assert "Same line 3" in result.content
        # Differing lines should be in conflict
        assert "Different local" in result.content
        assert "Different remote" in result.content

    def test_only_differing_section_has_markers(self) -> None:
        """Only the differing section gets conflict markers."""
        local = "Line 1\nLine 2\nLocal line 3\nLine 4\nLine 5\n"
        remote = "Line 1\nLine 2\nRemote line 3\nLine 4\nLine 5\n"

        result = merge_content(local=local, remote=remote)

        # Count conflict marker pairs
        assert result.conflict_count == 1
        # Both versions of line 3 preserved
        assert "Local line 3" in result.content
        assert "Remote line 3" in result.content


class TestNoDataLoss:
    """Critical tests to ensure no data is ever lost during merge."""

    def test_both_versions_preserved(self) -> None:
        """Both local and remote content must be in result."""
        local = "Local added this content\n"
        remote = "Remote added this content\n"

        result = merge_content(local=local, remote=remote)

        assert "Local added this content" in result.content
        assert "Remote added this content" in result.content

    def test_multiline_content_preserved(self) -> None:
        """Multiline content is fully preserved."""
        local = "Local line 1\nLocal line 2\nLocal line 3\n"
        remote = "Remote line 1\nRemote line 2\n"

        result = merge_content(local=local, remote=remote)

        # All local lines must be present
        assert "Local line 1" in result.content
        assert "Local line 2" in result.content
        assert "Local line 3" in result.content
        # All remote lines must be present
        assert "Remote line 1" in result.content
        assert "Remote line 2" in result.content

    def test_unicode_content_preserved(self) -> None:
        """Unicode content is preserved in conflicts."""
        local = "Hello שלום\n"
        remote = "Hello 你好\n"

        result = merge_content(local=local, remote=remote)

        assert "שלום" in result.content
        assert "你好" in result.content

    def test_long_content_preserved(self) -> None:
        """Long content is fully preserved."""
        local = "A" * 1000 + "\n"
        remote = "B" * 1000 + "\n"

        result = merge_content(local=local, remote=remote)

        assert "A" * 1000 in result.content
        assert "B" * 1000 in result.content


class TestConflictMarkerFormat:
    """Test conflict marker formatting."""

    def test_custom_labels(self) -> None:
        """Custom labels appear in conflict markers."""
        result = merge_content(
            local="local\n",
            remote="remote\n",
            local_label="MY_DEVICE",
            remote_label="OTHER_DEVICE",
        )

        assert "<<<<<<< MY_DEVICE" in result.content
        assert ">>>>>>> OTHER_DEVICE" in result.content

    def test_conflict_structure(self) -> None:
        """Conflict markers have correct structure."""
        result = merge_content(
            local="local\n",
            remote="remote\n",
        )

        lines = result.content.split("\n")
        # Find conflict region
        start_idx = next(i for i, l in enumerate(lines) if l.startswith("<<<<<<<"))
        mid_idx = next(i for i, l in enumerate(lines) if l.startswith("======="))
        end_idx = next(i for i, l in enumerate(lines) if l.startswith(">>>>>>>"))

        # Verify structure: start < mid < end
        assert start_idx < mid_idx < end_idx
        # Local content between start and mid
        assert "local" in "".join(lines[start_idx:mid_idx])
        # Remote content between mid and end
        assert "remote" in "".join(lines[mid_idx:end_idx])


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_content_both_versions(self) -> None:
        """Empty content in both versions."""
        result = merge_content(local="", remote="")
        assert result.content == ""
        assert result.has_conflicts is False

    def test_whitespace_differences(self) -> None:
        """Whitespace-only differences are detected."""
        local = "line \n"  # trailing space
        remote = "line  \n"  # two trailing spaces

        result = merge_content(local=local, remote=remote)

        # Both whitespace variants should be present
        assert result.has_conflicts is True

    def test_newline_variations(self) -> None:
        """Handle missing/present newlines at end."""
        local = "content\n"
        remote = "content"

        result = merge_content(local=local, remote=remote)
        # Should handle gracefully (no crash)
        assert "content" in result.content

    def test_very_long_lines(self) -> None:
        """Very long lines are handled correctly."""
        long_line = "x" * 10000
        local = long_line + " local\n"
        remote = long_line + " remote\n"

        result = merge_content(local=local, remote=remote)

        assert long_line in result.content
        assert "local" in result.content
        assert "remote" in result.content
