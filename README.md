# Voice Rewrite

Minimal MVP for note-taking application with hierarchical tags.

## Features
- Hierarchical tag system
- Three-pane interface (Tags, Notes List, Note Detail)
- SQLite database backend
- Fully typed Python code
- Clean architecture with separation of concerns

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

## MVP Limitations
- No editing notes or tags in UI (use DB directly for now)
- Read-only interface
- No keyboard shortcuts yet
- No audio recording functionality (coming in future iterations)

## Project Structure
- `src/core/` - Business logic and data access
- `src/ui/` - User interface components
- All code is fully typed and documented
