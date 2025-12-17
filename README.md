# Voice Rewrite

Minimal MVP for note-taking application with hierarchical tags.

## Features
- Hierarchical tag system
- Three-pane interface (Tags, Notes List, Note Detail)
- SQLite database backend
- Fully typed Python code
- Clean architecture with separation of concerns
- Search with tag: syntax and free-text
- Hierarchical tag filtering (parent includes children)
- AND logic for multiple search terms
- Comprehensive test suite (unit and integration tests)

## Requirements
- Python 3.10 or higher
- PySide6

## Installation

### Create Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Linux/Mac
# or
.venv\Scripts\activate  # On Windows
```

### Install Dependencies
```bash
pip install -r requirements.txt
```

### For Development
```bash
pip install -r requirements-dev.txt
```

## Usage

### Basic Usage
```bash
python -m src.main
```

### Custom Configuration Directory
```bash
python -m src.main -d /path/to/custom/config
# or
python -m src.main --config-dir /path/to/custom/config
```

### Future: Implementation Selection (not yet implemented)
```bash
# Example: Select media player implementation
python -m src.main --player=vlc

# Example: Select waveform display implementation
python -m src.main --waveform=matplotlib
```

## Testing

### Run All Tests
```bash
pytest
```

### Run Unit Tests Only
```bash
pytest tests/unit -m unit
```

### Run Integration Tests Only
```bash
pytest tests/integration -m integration
```

### Run with Coverage Report
```bash
pytest --cov=src --cov-report=html
# Open htmlcov/index.html in browser to view coverage
```

### Run Specific Test File
```bash
pytest tests/unit/test_database.py
```

### Run Specific Test Class or Function
```bash
pytest tests/unit/test_database.py::TestSearchNotes
pytest tests/unit/test_database.py::TestSearchNotes::test_text_search_only
```

### Test Data
The test suite uses a pre-populated database with:
- 14 tags in hierarchical structure (Work/Projects/VoiceRewrite, Geography/Europe/France/Paris, etc.)
- 6 notes with various tag combinations
- Hebrew text support testing
- Multiple notes per tag for comprehensive testing

## Development

### Type Checking
```bash
mypy src/
```

### Code Formatting
```bash
black src/
```

## Database Location
- Default: `~/.config/voicerewrite/notes.db`
- Custom: `<config-dir>/notes.db` when using `-d` flag

## Adding Sample Data
Since this is a read-only MVP, add notes and tags directly to the database:

```sql
-- Add some tags
INSERT INTO tags (name, parent_id) VALUES ('Work', NULL);
INSERT INTO tags (name, parent_id) VALUES ('Meetings', 1);
INSERT INTO tags (name, parent_id) VALUES ('Personal', NULL);

-- Add a note
INSERT INTO notes (created_at, content, modified_at, deleted_at)
VALUES (datetime('now'), 'This is my first note!', NULL, NULL);

-- Tag the note
INSERT INTO note_tags (note_id, tag_id) VALUES (1, 2);
```

## Search Syntax

### Free-text Search
```
meeting
hello world
```
Searches note content (case-insensitive)

### Tag Search
```
tag:Work
tag:Europe/France/Paris
```
Searches by tag. Hierarchical paths supported. Parent tags include children.

### Combined Search (AND logic)
```
tag:Work meeting
tag:Personal tag:Family reunion
```
Multiple terms are combined with AND logic:
- `tag:A tag:B` - notes must have (A or descendants) AND (B or descendants)
- `tag:A hello` - notes must have (A or descendants) AND contain "hello"

## MVP Limitations
- No editing notes or tags in UI (use DB directly for now)
- Read-only interface
- No keyboard shortcuts yet
- No audio recording functionality (coming in future iterations)

## Project Structure
- `src/core/` - Business logic and data access (zero Qt dependencies)
- `src/ui/` - User interface components (PySide6)
- `tests/` - Test suite (unit and integration tests)
- All code is fully typed and documented

## Architecture

### Critical Design Principle
The application has three modes (current and future):
1. **GUI mode** (current) - PySide6 interface
2. **CLI mode** (future) - Command-line interface
3. **Web server mode** (future) - HTTP API

Therefore, `src/core/` has **zero Qt dependencies** and can be imported by CLI/web modes.
