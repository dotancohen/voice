# Testing Documentation

## Test Suite Overview

The Voice Rewrite test suite provides comprehensive coverage of both core functionality and UI components using pytest, pytest-qt, and pytest-cov.

## Test Structure

```
tests/
├── conftest.py                      # Shared fixtures and configuration
├── unit/                           # Unit tests (no UI)
│   ├── __init__.py
│   ├── test_database.py            # Database operations
│   └── test_config.py              # Configuration management
└── integration/                    # Integration tests (with Qt)
    ├── __init__.py
    ├── test_tags_pane.py           # Tags pane functionality
    ├── test_notes_list_pane.py     # Notes list and display
    └── test_search.py              # Complete search flow
```

## Running Tests

### Quick Start
```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html
```

### Selective Testing
```bash
# Unit tests only (fast)
pytest tests/unit

# Integration tests only (requires Qt)
pytest tests/integration

# Specific test file
pytest tests/unit/test_database.py

# Specific test class
pytest tests/unit/test_database.py::TestSearchNotes

# Specific test function
pytest tests/unit/test_database.py::TestSearchNotes::test_text_search_only

# Tests matching pattern
pytest -k "search"
```

### Test Markers
```bash
# Run tests marked as "unit"
pytest -m unit

# Run tests marked as "integration"
pytest -m integration

# Skip slow tests
pytest -m "not slow"
```

## Test Coverage

### Unit Tests for `src/core/database.py`

**TestDatabaseInit** - Database initialization
- ✓ Creates schema (notes, tags, note_tags tables)
- ✓ Creates indexes

**TestGetAllNotes** - Fetching all notes
- ✓ Returns all non-deleted notes
- ✓ Excludes deleted notes
- ✓ Returns empty list for empty database
- ✓ Includes tag names

**TestGetNote** - Fetching single note
- ✓ Returns note by ID
- ✓ Returns None for non-existent note
- ✓ Includes associated tags

**TestGetAllTags** - Fetching all tags
- ✓ Returns all tags
- ✓ Includes parent_id for hierarchy
- ✓ Returns empty list for empty database

**TestGetTagDescendants** - Hierarchical tag navigation
- ✓ Returns tag itself and all descendants
- ✓ Returns only self for leaf tags
- ✓ Handles deep hierarchies (3+ levels)

**TestGetTag** - Fetching single tag
- ✓ Returns tag by ID
- ✓ Returns None for non-existent tag

**TestGetTagsByName** - Finding tags by name
- ✓ Finds tag by exact name
- ✓ Case-insensitive search
- ✓ Returns empty for no match

**TestGetTagByPath** - Hierarchical path navigation
- ✓ Finds tag by simple path ("Work")
- ✓ Finds tag by hierarchical path ("Europe/France/Paris")
- ✓ Case-insensitive path navigation
- ✓ Returns None for invalid path
- ✓ Handles trailing slashes

**TestSearchNotes** - Search with hierarchical AND logic
- ✓ Text search only
- ✓ Text search case-insensitive
- ✓ Hebrew text search
- ✓ Single tag group (includes descendants)
- ✓ Multiple tag groups AND logic
- ✓ Parent tag includes children
- ✓ Combined text and tags
- ✓ No results for non-matching search
- ✓ Empty search behavior

**TestFilterNotes** - Legacy OR-based filtering
- ✓ Filters by tag IDs
- ✓ Returns all for empty list

### Unit Tests for `src/core/config.py`

**TestConfigInit** - Configuration initialization
- ✓ Creates default config directory
- ✓ Creates custom config directory
- ✓ Creates config file

**TestLoadConfig** - Loading configuration
- ✓ Loads existing config
- ✓ Creates default if missing
- ✓ Handles invalid JSON (falls back to default)

**TestSaveConfig** - Saving configuration
- ✓ Saves config to JSON file
- ✓ Saved config is loadable

**TestGetSet** - Get/set operations
- ✓ Get returns stored value
- ✓ Get returns default for missing key
- ✓ Set updates value
- ✓ Set creates new key

**TestGetConfigDir** - Directory access
- ✓ Returns config directory path

**TestGetWarningColor** - Theme colors
- ✓ Returns warning color from config
- ✓ Returns default if missing
- ✓ Custom warning color support

**TestDefaultConfig** - Default values
- ✓ Default config structure
- ✓ Default themes structure
- ✓ Database file path is absolute

### Integration Tests for `ui/tags_pane.py`

**TestTagsPaneInit**
- ✓ Creates tags pane
- ✓ Loads tags on initialization

**TestTagTreeDisplay**
- ✓ Displays root tags
- ✓ Displays hierarchy correctly
- ✓ Displays deep hierarchies (3+ levels)
- ✓ Tree is expanded by default

**TestTagSelection**
- ✓ Clicking tag emits signal
- ✓ Emits correct tag ID
- ✓ Clicking child tag works

**TestTagsPaneReadOnly**
- ✓ Tree is not editable (NoEditTriggers)

### Integration Tests for `ui/notes_list_pane.py`

**TestNotesListPaneInit**
- ✓ Creates notes list pane
- ✓ Loads notes on initialization

**TestNoteDisplay**
- ✓ Displays all notes
- ✓ Two-line format (timestamp + content)
- ✓ Long content truncated with ellipsis
- ✓ Hebrew text displays correctly

**TestNoteSelection**
- ✓ Clicking note emits signal
- ✓ Emits correct note ID

**TestSearchField**
- ✓ Search field has appropriate placeholder
- ✓ Search button triggers search
- ✓ Return key triggers search
- ✓ Clear button clears search

**TestFreeTextSearch**
- ✓ Searches note content
- ✓ Case-insensitive search
- ✓ Hebrew text search

**TestTagFiltering**
- ✓ Filter by tag with single match
- ✓ Filter includes child tags
- ✓ Appends to existing search

**TestColorManagement**
- ✓ Default text color is white
- ✓ Editing restores white color

### Integration Tests for Search Functionality

**TestTagSyntax**
- ✓ Single tag search
- ✓ Hierarchical tag path
- ✓ Case-insensitive tag search

**TestHierarchicalSearch**
- ✓ Parent tag includes children
- ✓ Parent includes deeply nested children

**TestMultipleTagsAND**
- ✓ Two tags AND logic
- ✓ Parent and child tag search
- ✓ Three tags AND logic

**TestCombinedSearch**
- ✓ Text and single tag
- ✓ Text and multiple tags
- ✓ Text with hierarchical tag
- ✓ Multiple text words with tags

**TestSearchParsing**
- ✓ Parses mixed text and tags
- ✓ Parses hierarchical paths
- ✓ Parses empty string

**TestSearchEdgeCases**
- ✓ Non-existent tag returns no results
- ✓ Empty search shows all notes
- ✓ Tag with no matching notes
- ✓ Conflicting criteria returns nothing

## Test Data

The test suite uses a pre-populated database with realistic test data:

### Tag Hierarchy
```
Work (1)
├── Projects (2)
│   └── VoiceRewrite (3)
└── Meetings (4)

Personal (5)
├── Family (6)
└── Health (7)

Geography (8)
├── Europe (9)
│   ├── France (10)
│   │   └── Paris (11)
│   └── Germany (12)
└── Asia (13)
    └── Israel (14)
```

### Notes
1. "Meeting notes from project kickoff" - Tags: Work, Projects, Meetings
2. "Remember to update documentation" - Tags: Work, Projects, VoiceRewrite
3. "Doctor appointment next Tuesday" - Tags: Personal, Health
4. "Family reunion in Paris" - Tags: Personal, Family, France, Paris
5. "Trip to Israel planning" - Tags: Personal, Asia, Israel
6. "שלום עולם - Hebrew text test" - Tags: Personal

## Suggested Additional Tests

### High Priority

1. **Performance Tests**
   - Large database (1000+ notes)
   - Deep tag hierarchies (10+ levels)
   - Complex search queries
   - Rapid clicking/interaction

2. **Edge Cases**
   - Special characters in note content
   - Very long note content (>10k characters)
   - Malformed timestamps
   - Circular tag references (shouldn't happen but test handling)
   - Empty tag names
   - Duplicate tag names in different hierarchies

3. **Error Handling**
   - Database connection failures
   - Corrupted database
   - Missing config file during operation
   - Invalid config JSON during operation
   - Permission errors on config/database files

4. **Concurrency**
   - Multiple notes list panes
   - Simultaneous searches
   - Database access from multiple components

### Medium Priority

5. **UI Interaction Tests**
   - Resizing panes
   - Window minimize/maximize
   - Focus management
   - Keyboard navigation (when implemented)
   - Copy/paste from notes (when implemented)

6. **Data Integrity**
   - Foreign key constraints
   - Transaction rollback on errors
   - Soft delete preservation
   - Tag deletion cascade behavior

7. **Search Combinations**
   - Very long search queries
   - Many tag: terms (10+)
   - Special characters in search
   - Empty tag: syntax (tag: with no name)

8. **Configuration**
   - Config migration (version upgrades)
   - Missing keys in config
   - Invalid color values
   - Custom database locations

### Low Priority

9. **Localization**
   - Right-to-left text (Hebrew, Arabic)
   - Mixed LTR/RTL content
   - Various Unicode characters
   - Emoji in content

10. **Platform-Specific**
    - Windows path handling
    - macOS-specific behavior
    - Linux permissions
    - Different Qt versions

11. **Accessibility**
    - Screen reader compatibility
    - High contrast mode
    - Font size changes
    - Color blind modes

## Coverage Goals

- **Overall**: >80% line coverage
- **Core modules** (`src/core/`): >90% line coverage
- **UI modules** (`src/ui/`): >70% line coverage
- **Critical paths** (search, tag filtering): 100% coverage

## Running Coverage Reports

```bash
# Generate HTML coverage report
pytest --cov=src --cov-report=html

# Open report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows

# Generate terminal report
pytest --cov=src --cov-report=term-missing

# Fail if coverage below threshold
pytest --cov=src --cov-fail-under=80
```

## Continuous Integration

For CI/CD integration, add to your workflow:

```yaml
- name: Run tests
  run: |
    pip install -r requirements-dev.txt
    pytest --cov=src --cov-report=xml --junitxml=test-results.xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
  with:
    files: ./coverage.xml
```

## Test Maintenance

- Update fixtures when adding new features
- Keep test data realistic and representative
- Document complex test scenarios
- Review and update tests when refactoring
- Run full test suite before committing
- Maintain >80% coverage for new code
