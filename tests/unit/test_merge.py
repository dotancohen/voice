"""Unit tests for the merge module.

Tests 3-way merge functionality to ensure no data loss during sync.
"""

from __future__ import annotations

import pytest

from core.merge import MergeResult, merge_content


class TestMergeBasics:
    """Test basic merge functionality."""

    def test_identical_content_no_conflict(self) -> None:
        """When all versions are identical, no conflict."""
        result = merge_content(
            base="Hello\nWorld\n",
            local="Hello\nWorld\n",
            remote="Hello\nWorld\n",
        )
        assert result.content == "Hello\nWorld\n"
        assert result.has_conflicts is False
        assert result.conflict_count == 0

    def test_only_remote_changed(self) -> None:
        """When only remote changed, use remote version."""
        result = merge_content(
            base="Original\n",
            local="Original\n",
            remote="Modified\n",
        )
        assert result.content == "Modified\n"
        assert result.has_conflicts is False

    def test_only_local_changed(self) -> None:
        """When only local changed, use local version."""
        result = merge_content(
            base="Original\n",
            local="Modified\n",
            remote="Original\n",
        )
        assert result.content == "Modified\n"
        assert result.has_conflicts is False

    def test_both_same_change(self) -> None:
        """When both made same change, no conflict."""
        result = merge_content(
            base="Original\n",
            local="Same change\n",
            remote="Same change\n",
        )
        assert result.content == "Same change\n"
        assert result.has_conflicts is False


class TestMergeCleanMerge:
    """Test clean merge scenarios (non-overlapping changes)."""

    def test_non_overlapping_line_changes(self) -> None:
        """Non-overlapping changes merge cleanly."""
        base = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
        local = "Line 1\nLocal edit\nLine 3\nLine 4\nLine 5\n"
        remote = "Line 1\nLine 2\nLine 3\nLine 4\nRemote edit\n"

        result = merge_content(base=base, local=local, remote=remote)

        assert result.has_conflicts is False
        assert "Local edit" in result.content
        assert "Remote edit" in result.content

    def test_local_adds_line_remote_edits(self) -> None:
        """Local adds a line, remote edits existing - should merge."""
        base = "Line 1\nLine 2\n"
        local = "Line 1\nNew line\nLine 2\n"
        remote = "Line 1\nModified line 2\n"

        result = merge_content(base=base, local=local, remote=remote)

        # Both changes should be present
        assert "New line" in result.content
        assert "Modified" in result.content


class TestMergeConflicts:
    """Test conflict detection and marking."""

    def test_conflicting_same_line_edit(self) -> None:
        """Edits to same line create conflict with markers."""
        base = "Line 1\nLine 2\nLine 3\n"
        local = "Line 1\nLocal version\nLine 3\n"
        remote = "Line 1\nRemote version\nLine 3\n"

        result = merge_content(base=base, local=local, remote=remote)

        assert result.has_conflicts is True
        assert result.conflict_count >= 1
        assert "<<<<<<< LOCAL" in result.content
        assert "=======" in result.content
        assert ">>>>>>> REMOTE" in result.content
        # Both versions preserved
        assert "Local version" in result.content
        assert "Remote version" in result.content

    def test_conflict_preserves_unchanged_lines(self) -> None:
        """Conflict markers only affect conflicting region."""
        base = "Line 1\nLine 2\nLine 3\n"
        local = "Line 1\nLocal\nLine 3\n"
        remote = "Line 1\nRemote\nLine 3\n"

        result = merge_content(base=base, local=local, remote=remote)

        # Unchanged lines should be present without markers
        assert "Line 1\n" in result.content
        assert "Line 3\n" in result.content


class TestNoDataLoss:
    """Critical tests to ensure no data is ever lost during merge."""

    def test_no_data_loss_both_add_different_content(self) -> None:
        """When both add different content, both must be preserved."""
        base = ""
        local = "Local added this content\n"
        remote = "Remote added this content\n"

        result = merge_content(base=base, local=local, remote=remote)

        # Both additions must be in the result
        assert "Local added this content" in result.content
        assert "Remote added this content" in result.content

    def test_no_data_loss_conflicting_multiline(self) -> None:
        """Multiline conflicts preserve all content from both sides."""
        base = "Original content\n"
        local = "Local line 1\nLocal line 2\nLocal line 3\n"
        remote = "Remote line 1\nRemote line 2\n"

        result = merge_content(base=base, local=local, remote=remote)

        # All local lines must be present
        assert "Local line 1" in result.content
        assert "Local line 2" in result.content
        assert "Local line 3" in result.content
        # All remote lines must be present
        assert "Remote line 1" in result.content
        assert "Remote line 2" in result.content

    def test_no_data_loss_unicode_content(self) -> None:
        """Unicode content is preserved in conflicts."""
        base = "Hello\n"
        local = "Hello שלום\n"
        remote = "Hello 你好\n"

        result = merge_content(base=base, local=local, remote=remote)

        # Both unicode strings must be present
        assert "שלום" in result.content
        assert "你好" in result.content

    def test_no_data_loss_empty_base(self) -> None:
        """With empty base, all content is preserved."""
        base = ""
        local = "Content A\n"
        remote = "Content B\n"

        result = merge_content(base=base, local=local, remote=remote)

        assert "Content A" in result.content
        assert "Content B" in result.content

    def test_no_data_loss_long_content(self) -> None:
        """Long content is fully preserved in conflicts."""
        base = "short\n"
        local = "A" * 1000 + "\n"
        remote = "B" * 1000 + "\n"

        result = merge_content(base=base, local=local, remote=remote)

        assert "A" * 1000 in result.content
        assert "B" * 1000 in result.content


class TestConflictMarkerFormat:
    """Test conflict marker formatting."""

    def test_custom_labels(self) -> None:
        """Custom labels appear in conflict markers."""
        result = merge_content(
            base="a\n",
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
            base="base\n",
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

    def test_empty_content_all_versions(self) -> None:
        """Empty content in all versions."""
        result = merge_content(base="", local="", remote="")
        assert result.content == ""
        assert result.has_conflicts is False

    def test_whitespace_only_differences(self) -> None:
        """Whitespace-only differences are detected."""
        base = "line\n"
        local = "line \n"  # trailing space
        remote = "line  \n"  # two trailing spaces

        result = merge_content(base=base, local=local, remote=remote)

        # Both whitespace variants should be present
        assert "line " in result.content

    def test_newline_at_end_variations(self) -> None:
        """Handle missing/present newlines at end."""
        base = "content"
        local = "content\n"
        remote = "content"

        result = merge_content(base=base, local=local, remote=remote)
        # Should handle gracefully (no crash)
        assert "content" in result.content

    def test_very_long_lines(self) -> None:
        """Very long lines are handled correctly."""
        long_line = "x" * 10000
        base = long_line + "\n"
        local = long_line + " local\n"
        remote = long_line + " remote\n"

        result = merge_content(base=base, local=local, remote=remote)

        assert long_line in result.content
        assert "local" in result.content
        assert "remote" in result.content
