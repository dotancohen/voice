# Voice Rewrite

Note-taking application with hierarchical tags, available as GUI, CLI, and Web API.

## Features
- Hierarchical tag system with unlimited nesting
- **GUI Mode**: Three-pane PySide6 interface with dark/light theme support
- **CLI Mode**: Command-line interface with JSON/CSV export
- **Web API Mode**: RESTful HTTP API with JSON responses
- SQLite database backend
- Fully typed Python code
- Clean architecture with complete core/UI separation
- Search with tag: syntax and free-text
- Hierarchical tag filtering (parent includes children)
- AND logic for multiple search terms
- Comprehensive test suite (unit + GUI + CLI + web tests)

## Requirements
- Python 3.10 or higher
- PySide6 + pyqtdarktheme (for GUI mode)
- Flask + Flask-CORS (for Web API mode)

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

### GUI Mode

Launch the graphical interface (default dark theme):
```bash
python -m src.main
```

Launch in light theme:
```bash
python -m src.main --theme light
```

Launch in dark theme (explicit):
```bash
python -m src.main --theme dark
```

With custom configuration directory:
```bash
python -m src.main -d /path/to/custom/config
```

Combine options:
```bash
python -m src.main --theme light -d /path/to/custom/config
```

### CLI Mode

List all notes:
```bash
python -m src.cli list-notes
python -m src.cli --format json list-notes  # JSON output
python -m src.cli --format csv list-notes   # CSV output
```

Show specific note:
```bash
python -m src.cli show-note 1
python -m src.cli --format json show-note 1
```

List tags (hierarchical):
```bash
python -m src.cli list-tags
```

Search notes:
```bash
# Search by text
python -m src.cli search --text "meeting"

# Search by tag
python -m src.cli search --tag Work

# Search by hierarchical tag path
python -m src.cli search --tag Geography/Europe/France/Paris

# Multiple tags (AND logic)
python -m src.cli search --tag Work --tag Work/Projects

# Combined text and tags
python -m src.cli search --text "meeting" --tag Work

# JSON output
python -m src.cli --format json search --tag Personal
```

Custom configuration directory (all commands):
```bash
python -m src.cli -d /path/to/config list-notes
```

### Web API Mode

Start the Flask web server:
```bash
python -m src.web
```

Server runs on `http://127.0.0.1:5000` by default.

Custom host/port:
```bash
python -m src.web --host 0.0.0.0 --port 8080
```

Enable debug mode:
```bash
python -m src.web --debug
```

**API Endpoints:**

List all notes:
```bash
curl http://127.0.0.1:5000/api/notes
```

Get specific note:
```bash
curl http://127.0.0.1:5000/api/notes/1
```

List all tags:
```bash
curl http://127.0.0.1:5000/api/tags
```

Search notes:
```bash
# Search by text
curl "http://127.0.0.1:5000/api/search?text=meeting"

# Search by tag
curl "http://127.0.0.1:5000/api/search?tag=Work"

# Search by hierarchical tag
curl "http://127.0.0.1:5000/api/search?tag=Geography/Europe/France/Paris"

# Multiple tags (AND logic)
curl "http://127.0.0.1:5000/api/search?tag=Work&tag=Work/Projects"

# Combined text and tags
curl "http://127.0.0.1:5000/api/search?text=meeting&tag=Work"
```

Health check:
```bash
curl http://127.0.0.1:5000/api/health
```

All endpoints return JSON. CORS is enabled for cross-origin requests.

## Testing

The test suite is organized by interface type for clean separation:
- **Unit tests** (`tests/unit/`) - Core functionality, no dependencies
- **GUI tests** (`tests/gui/`) - GUI components, requires Qt/PySide6
- **CLI tests** (`tests/cli/`) - Command-line interface
- **Web tests** (`tests/web/`) - Flask REST API endpoints

### Run All Tests
```bash
pytest
```

### Run Tests by Type
```bash
# Unit tests only (fast, no dependencies)
pytest tests/unit

# GUI tests only (requires Qt/PySide6)
pytest tests/gui

# CLI tests only
pytest tests/cli

# Web API tests only (Flask)
pytest tests/web

# By marker
pytest -m unit   # Unit tests
pytest -m gui    # GUI tests
pytest -m cli    # CLI tests
pytest -m web    # Web API tests
```

### Run with Coverage Report
```bash
pytest --cov=src --cov-report=html
# Open htmlcov/index.html in browser to view coverage
```

### Run Specific Test File
```bash
pytest tests/unit/test_database.py
pytest tests/cli/test_cli_search.py
```

### Run Specific Test Class or Function
```bash
pytest tests/unit/test_database.py::TestSearchNotes
pytest tests/cli/test_cli_search.py::TestSearchText::test_search_by_text
```

### Test Data
The test suite uses a pre-populated database with:
- 14 tags in hierarchical structure (Work/Projects/VoiceRewrite, Geography/Europe/France/Paris, etc.)
- 6 notes with various tag combinations
- Hebrew text support testing
- Multiple notes per tag for comprehensive testing

See `TESTING.md` for detailed test documentation.

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
- `src/ui/` - GUI components (PySide6)
- `src/cli.py` - Command-line interface
- `src/web.py` - Flask REST API
- `src/main.py` - GUI entry point
- `tests/unit/` - Core functionality tests
- `tests/gui/` - GUI integration tests
- `tests/cli/` - CLI tests
- `tests/web/` - Web API tests
- All code is fully typed and documented

## Architecture

### Critical Design Principle
The application has three modes:
1. **GUI mode** - PySide6 interface (three-pane layout)
2. **CLI mode** - Command-line interface with JSON/CSV/text output
3. **Web API mode** - Flask REST API with JSON responses

Therefore, `src/core/` has **zero Qt dependencies** and can be imported by all interface modes.

### Test Organization
Tests are separated by interface type for complete independence:
- `tests/unit/` - Core functionality (database, config) - 55 tests
- `tests/gui/` - GUI components (requires Qt) - 49 tests
- `tests/cli/` - CLI commands (subprocess) - 38 tests
- `tests/web/` - Web API endpoints (Flask test client) - 38 tests
