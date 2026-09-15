#!/usr/bin/env python3
"""Web API for Voice.

This module provides a RESTful HTTP API for interacting with notes and tags.
Uses only core/ modules - no Qt/PySide6 dependencies.

Endpoints:
    GET  /api/notes                      List all notes
    POST /api/notes                      Create a new note
    GET  /api/notes/<id>                 Get specific note
    PUT  /api/notes/<id>                 Update a note
    DELETE /api/notes/<id>               Delete a note (soft delete)
    GET  /api/notes/<id>/attachments     List attachments for a note
    GET  /api/audiofiles/<id>            Get audio file details
    GET  /api/audiofiles/<id>/locations  Where the recording's copies are
    POST /api/audiofiles/<id>/remove-local  Remove this device's copy once the bucket or a holding device confirms it holds the file
    GET  /api/issues                     What needs the user's attention
    GET  /api/storage/upload-limit       The account's upload limit
    PUT  /api/storage/upload-limit       Set it: {"megabytes": 250}
    GET  /api/tags                       List all tags
    GET  /api/search                     Search notes

All endpoints return JSON responses.
IDs are UUID7 hex strings (32 characters, no hyphens).

Query parameters for /api/search:
    - text: Text to search for in note content
    - tag: Tag path to filter by (can be specified multiple times for AND logic)

POST /api/notes body:
    - content: Note content (string, required)

PUT /api/notes/<id> body:
    - content: New note content (string, required)
"""

from __future__ import annotations

import argparse
import functools
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from flask import Flask, jsonify, request, Response
from flask_cors import CORS

from src.core.config import Config
from src.core.conflicts import ConflictManager
from src.core.database import Database
from src.core.validation import ValidationError, validate_uuid_hex

logger = logging.getLogger(__name__)

# Global database instance
db: Optional[Database] = None


def api_endpoint(func: Callable) -> Callable:
    """Decorator for consistent API error handling.

    Catches ValidationError (400) and Exception (500) with proper
    JSON error responses and logging.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except ValidationError as e:
            return jsonify({"error": f"Invalid {e.field}: {e.message}"}), 400
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            return jsonify({"error": str(e)}), 500
    return wrapper


# Where this installation keeps its recordings, so that a note removed for
# good takes its files with it.
audiofile_directory: Optional[str] = None


def create_app(config_dir: Optional[Path] = None, root: Optional[Path] = None) -> Flask:
    """Create and configure Flask application.

    Args:
        config_dir: Custom configuration directory (default: None)

    Returns:
        Configured Flask application
    """
    app = Flask(__name__)
    CORS(app)  # Enable CORS for all routes

    # Initialize config and database
    config = Config(config_dir=config_dir, root=root)
    db_path_str = config.get("database_file")
    db_path = Path(db_path_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    global db, audiofile_directory
    db = Database(db_path)
    audiofile_directory = config.get_audiofile_directory()
    from src.core.synced_settings import reconcile_transcription_settings
    reconcile_transcription_settings(config, db)

    logger.info(f"Web API initialized with database: {db_path}")

    # Error handlers
    @app.errorhandler(404)
    def not_found(error: Any) -> tuple[Response, int]:
        """Handle 404 errors."""
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(error: Any) -> tuple[Response, int]:
        """Handle 500 errors."""
        logger.error(f"Internal error: {error}")
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(ValidationError)
    def validation_error(error: ValidationError) -> tuple[Response, int]:
        """Handle validation errors."""
        logger.warning(f"Validation error: {error.field} - {error.message}")
        return jsonify({"error": f"Invalid {error.field}: {error.message}"}), 400

    # Routes
    @app.route("/api/notes", methods=["GET"])
    @api_endpoint
    def get_notes() -> Response:
        """Get all notes."""
        notes = db.get_all_notes()
        return jsonify(notes)

    @app.route("/api/notes", methods=["POST"])
    @api_endpoint
    def create_note() -> tuple[Response, int]:
        """Create a new note."""
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body is required"}), 400

        content = data.get("content")
        if not content:
            return jsonify({"error": "Content is required"}), 400

        note_id = db.create_note(content)
        logger.info(f"Created note {note_id} via API")
        return jsonify({"id": note_id, "content": content}), 201

    @app.route("/api/notes/<note_id>", methods=["GET"])
    @api_endpoint
    def get_note(note_id: str) -> tuple[Response, int]:
        """Get specific note by ID."""
        validate_uuid_hex(note_id, "note_id")
        note = db.get_note(note_id)
        if note:
            # Add conflict information
            conflict_mgr = ConflictManager(db)
            conflict_types = conflict_mgr.get_note_conflict_types(note["id"])
            note["has_conflicts"] = len(conflict_types) > 0
            note["conflict_types"] = conflict_types
            return jsonify(note), 200
        return jsonify({"error": f"Note {note_id} not found"}), 404

    @app.route("/api/notes/<note_id>", methods=["PUT"])
    @api_endpoint
    def update_note(note_id: str) -> tuple[Response, int]:
        """Update a note."""
        validate_uuid_hex(note_id, "note_id")
        note = db.get_note(note_id)
        if not note:
            return jsonify({"error": f"Note {note_id} not found"}), 404

        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body is required"}), 400

        content = data.get("content")
        if not content:
            return jsonify({"error": "Content is required"}), 400

        db.update_note(note_id, content)
        logger.info(f"Updated note {note_id} via API")
        updated_note = db.get_note(note_id)
        return jsonify(updated_note), 200

    @app.route("/api/notes/<note_id>", methods=["DELETE"])
    @api_endpoint
    def delete_note(note_id: str) -> tuple[Response, int]:
        """Delete a note (soft delete)."""
        validate_uuid_hex(note_id, "note_id")
        deleted = db.delete_note(note_id)
        if deleted:
            return jsonify({"message": f"Note {note_id} deleted"}), 200
        return jsonify({"error": f"Note {note_id} not found"}), 404

    @app.route("/api/maintenance/missing-data", methods=["GET"])
    @api_endpoint
    def survey_missing_data() -> Response:
        """What was never worked out: Recording lengths and creation dates.

        Changes nothing. Each entry says how many there are and whether it can
        be filled in at all.
        """
        from src.core import missing_data

        survey = missing_data.survey(db, config)
        return jsonify({
            "gaps": [
                {
                    "key": gap.key,
                    "description": gap.description,
                    "count": gap.count,
                    "calculable": gap.calculable,
                    "note": gap.note,
                }
                for gap in survey.gaps
            ],
            "total_calculable": survey.total_calculable,
        })

    @app.route("/api/maintenance/missing-data", methods=["POST"])
    @api_endpoint
    def calculate_missing_data() -> Response:
        """Calculate what can be calculated, and report what happened.

        Body (all optional): `durations`, `file_dates` as booleans to
        leave a kind of repair out, and `limit` to read at most that many
        Recordings in one run.
        """
        from src.core import missing_data

        body = request.get_json(silent=True) or {}
        report = missing_data.calculate_missing_data(
            db, config,
            durations=bool(body.get("durations", True)),
            file_dates=bool(body.get("file_dates", True)),
            limit=body.get("limit"),
        )
        return jsonify({
            "calculated": report.calculated,
            "failed": report.failed,
            "details": report.details,
            "total_calculated": report.total_calculated,
        })

    @app.route("/api/transcription-queue", methods=["GET"])
    @api_endpoint
    def transcription_queue() -> Response:
        """What is waiting to be transcribed on this machine, and what it cost.

        Three groups — `waiting`, `processing`, `completed` — newest first within
        each, plus `rate`: seconds of work per second of Recording on this
        machine, which is what the waiting estimates are worked out from.

        One queue for the whole installation, so this is the same queue the GUI,
        the TUI and the CLI show.

            curl http://localhost:5000/api/transcription-queue

        Query: `service` narrows the finished work to one transcription service.
        """
        from src.core import transcription_queue as queue_module

        view = queue_module.view(db, config, request.args.get("service"))
        return jsonify(queue_module.as_json(view))

    @app.route("/api/transcription-queue", methods=["POST"])
    @api_endpoint
    def transcription_queue_add() -> tuple[Response, int] | Response:
        """Put a Recording in the queue.

        Body: `audio_file_id`, and optionally `provider` (the transcription
        service's configuration: `provider_id`, `model`, `language`). Nothing is
        transcribed by this call — the GUI, or `cli transcription-queue --run`,
        does the work, one Recording at a time.

            curl -X POST http://localhost:5000/api/transcription-queue \
                -H 'Content-Type: application/json' \
                -d '{"audio_file_id": "01a0...", "provider": {"provider_id": "local_whisper"}}'
        """
        from src.core import transcription_queue as queue_module

        body = request.get_json(silent=True) or {}
        audio_file_id = body.get("audio_file_id")
        if not audio_file_id:
            return jsonify({"error": "audio_file_id is required"}), 400
        provider = body.get("provider") or {"provider_id": "local_whisper"}
        problem = queue_module.enqueue(db, config, audio_file_id, provider)
        if problem:
            return jsonify({"error": problem}), 400
        return jsonify({"queued": audio_file_id})

    @app.route("/api/transcription-queue/next", methods=["POST"])
    @api_endpoint
    def transcription_queue_next() -> tuple[Response, int] | Response:
        """Transcribe one waiting Recording next, ahead of the others.

        The Recording being worked on is not interrupted: it is minutes into
        work that would have to start again.

        Body: `audio_file_id`.
        """
        from src.core import transcription_queue as queue_module

        body = request.get_json(silent=True) or {}
        audio_file_id = body.get("audio_file_id")
        if not audio_file_id:
            return jsonify({"error": "audio_file_id is required"}), 400
        moved = queue_module.Queue(config.config_dir).do_next(audio_file_id)
        if not moved:
            return jsonify({"error": "That Recording is not waiting, or is already next"}), 400
        return jsonify({"next": audio_file_id})

    @app.route("/api/transcription-queue/remove", methods=["POST"])
    @api_endpoint
    def transcription_queue_remove() -> tuple[Response, int] | Response:
        """Take a waiting Recording out of the queue. Body: `audio_file_id`."""
        from src.core import transcription_queue as queue_module

        body = request.get_json(silent=True) or {}
        audio_file_id = body.get("audio_file_id")
        if not audio_file_id:
            return jsonify({"error": "audio_file_id is required"}), 400
        removed = queue_module.Queue(config.config_dir).remove(audio_file_id)
        if not removed:
            return jsonify({"error": "That Recording is not waiting"}), 400
        return jsonify({"removed": audio_file_id})

    @app.route("/api/transcription-queue/clear", methods=["POST"])
    @api_endpoint
    def transcription_queue_clear() -> Response:
        """Forget everything waiting. What is being worked on is not stopped."""
        from src.core import transcription_queue as queue_module

        return jsonify({"forgotten": queue_module.Queue(config.config_dir).clear()})

    @app.route("/api/trash", methods=["GET"])
    @api_endpoint
    def get_trash() -> Response:
        """The notes in the trash: deleted, still here, newest deletion first."""
        return jsonify({"notes": db.get_deleted_notes()})

    @app.route("/api/trash/<note_id>/recover", methods=["POST"])
    @api_endpoint
    def recover_note(note_id: str) -> tuple[Response, int]:
        """Take a note out of the trash."""
        validate_uuid_hex(note_id, "note_id")
        if db.undelete_note(note_id):
            return jsonify({"message": f"Note {note_id} recovered"}), 200
        return jsonify({"error": f"Note {note_id} is not in the trash"}), 404

    @app.route("/api/trash/<note_id>", methods=["DELETE"])
    @api_endpoint
    def purge_note(note_id: str) -> tuple[Response, int]:
        """Remove a note in the trash for good, on every device.

        Refuses a note that is not in the trash: deleting is one step and
        removing for good is another, so that neither can happen by accident.
        """
        validate_uuid_hex(note_id, "note_id")
        if not any(n["id"] == note_id for n in db.get_deleted_notes()):
            return jsonify({"error": f"Note {note_id} is not in the trash"}), 404
        from src.core.purge import remove_purged_files

        purged = db.purge_note(note_id)
        removed = remove_purged_files(purged, audiofile_directory)
        return jsonify({
            "message": f"Note {note_id} removed for good",
            "audio_files": [r["id"] for r in purged],
            "files_removed": len(removed),
        }), 200

    @app.route("/api/notes/<note_id>/attachments", methods=["GET"])
    @api_endpoint
    def get_note_attachments(note_id: str) -> tuple[Response, int]:
        """Get all attachments for a note.

        Returns list of attachments with their type and details.
        For audio_file type, includes audio file details inline.
        """
        validate_uuid_hex(note_id, "note_id")
        note = db.get_note(note_id)
        if not note:
            return jsonify({"error": f"Note {note_id} not found"}), 404

        # Get all attachments for the note
        attachments = db.get_attachments_for_note(note_id)

        # Enrich audio_file attachments with audio file details
        result = []
        for attachment in attachments:
            item = {
                "id": attachment["id"],
                "note_id": attachment["note_id"],
                "attachment_id": attachment["attachment_id"],
                "attachment_type": attachment["attachment_type"],
                "created_at": attachment["created_at"],
            }
            if attachment["attachment_type"] == "audio_file":
                audio_file = db.get_audio_file(attachment["attachment_id"])
                if audio_file:
                    item["audio_file"] = audio_file
            result.append(item)

        return jsonify({"attachments": result}), 200

    @app.route("/api/audiofiles/<audio_id>", methods=["GET"])
    @api_endpoint
    def get_audiofile(audio_id: str) -> tuple[Response, int]:
        """Get audio file details by ID."""
        validate_uuid_hex(audio_id, "audio_id")
        audio_file = db.get_audio_file(audio_id)
        if audio_file:
            return jsonify(audio_file), 200
        return jsonify({"error": f"Audio file {audio_id} not found"}), 404

    @app.route("/api/audiofiles/<audio_id>/locations", methods=["GET"])
    @api_endpoint
    def get_audiofile_locations(audio_id: str) -> tuple[Response, int]:
        """Where a recording's copies are (FILE-22)."""
        validate_uuid_hex(audio_id, "audio_id")
        if not db.get_audio_file(audio_id):
            return jsonify({"error": f"Audio file {audio_id} not found"}), 404
        return jsonify({"locations": db.file_locations(audio_id)}), 200

    @app.route("/api/audiofiles/<audio_id>/remove-local", methods=["POST"])
    @api_endpoint
    def remove_local_audiofile(audio_id: str) -> tuple[Response, int]:
        """Remove this device's copy of a recording (FILE-22) once the bucket or a
        device that holds it confirms now that it does (FILE-26); 409 with what
        each place answered when none confirmed."""
        validate_uuid_hex(audio_id, "audio_id")
        if not db.get_audio_file(audio_id):
            return jsonify({"error": f"Audio file {audio_id} not found"}), 404
        if not audiofile_directory:
            return jsonify({"error": "audiofile_directory is not configured"}), 400
        from voicecore import SyncClient

        try:
            sentence = SyncClient(str(config.get_config_dir())).remove_local_copy(audio_id)
        except Exception as e:  # noqa: BLE001 - the core's sentence is the answer
            return jsonify({"error": str(e)}), 409
        return jsonify({"removed": True, "sentence": sentence, "locations": db.file_locations(audio_id)}), 200

    @app.route("/api/issues", methods=["GET"])
    @api_endpoint
    def get_issues() -> tuple[Response, int]:
        """What needs the user's attention (ISSUE-1)."""
        return jsonify(db.issues(audiofile_directory, config.get_this_device_id_hex())), 200

    @app.route("/api/storage/upload-limit", methods=["GET"])
    @api_endpoint
    def get_upload_limit() -> tuple[Response, int]:
        """The account's upload limit (FILE-23)."""
        return jsonify({"max_upload_mb": db.max_upload_bytes() // (1024 * 1024)}), 200

    @app.route("/api/storage/upload-limit", methods=["PUT"])
    @api_endpoint
    def set_upload_limit() -> tuple[Response, int]:
        """Set the account's upload limit (FILE-23): {"megabytes": n}."""
        body = request.get_json(silent=True) or {}
        megabytes = body.get("megabytes")
        if not isinstance(megabytes, int) or isinstance(megabytes, bool):
            return jsonify({"error": "megabytes must be a whole number"}), 400
        try:
            db.set_max_upload_mb(megabytes)
        except Exception as e:  # noqa: BLE001 - the core's sentence is the answer
            return jsonify({"error": str(e)}), 400
        return jsonify({"max_upload_mb": db.max_upload_bytes() // (1024 * 1024)}), 200

    @app.route("/api/tags", methods=["GET"])
    @api_endpoint
    def get_tags() -> Response:
        """Get all tags."""
        tags = db.get_all_tags()
        return jsonify(tags)

    @app.route("/api/search", methods=["GET"])
    @api_endpoint
    def search_notes() -> tuple[Response, int]:
        """Search notes by text and/or tags."""
        text_query = request.args.get("text")
        tag_paths = request.args.getlist("tag")

        # Build tag_id_groups
        # For ambiguous tags, all matching tags' descendants go into ONE group (OR logic)
        tag_id_groups: List[List[bytes]] = []
        any_tag_not_found = False

        for tag_path in tag_paths:
            matching_tags = db.get_all_tags_by_path(tag_path)

            if matching_tags:
                # Collect all descendants from all matching tags into ONE group (OR logic)
                all_descendants: List[bytes] = []
                for tag in matching_tags:
                    descendants = db.get_tag_descendants(tag["id"])
                    all_descendants.extend(descendants)

                all_descendants = list(set(all_descendants))
                tag_id_groups.append(all_descendants)

                if len(matching_tags) > 1:
                    logger.info(f"Tag '{tag_path}' is ambiguous - matching {len(matching_tags)} tags (using OR logic)")
            else:
                logger.warning(f"Tag path '{tag_path}' not found")
                any_tag_not_found = True

        if any_tag_not_found:
            notes: List[Dict[str, Any]] = []
        else:
            notes = db.search_notes(
                text_query=text_query if text_query else None,
                tag_id_groups=tag_id_groups if tag_id_groups else None
            )

        return jsonify(notes), 200

    @app.route("/api/health", methods=["GET"])
    def health_check() -> tuple[Response, int]:
        """Health check endpoint.

        Returns:
            JSON response indicating service health
        """
        return jsonify({"status": "ok"}), 200

    return app


def add_web_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add web subparser and its arguments.

    Args:
        subparsers: Parent subparsers object to add web parser to
    """
    web_parser = subparsers.add_parser(
        "web",
        help="Start web API server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    web_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)"
    )

    web_parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to bind to (default: 5000)"
    )

    web_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )


def run(config_dir: Optional[Path], args: argparse.Namespace) -> int:
    """Run web server with given arguments.

    Args:
        config_dir: Custom configuration directory or None for default
        args: Parsed command-line arguments (should have host, port, debug attributes)

    Returns:
        Exit code (0 for success)
    """
    logger.info("Starting Voice Web API")
    if config_dir:
        logger.info(f"Using custom config directory: {config_dir}")

    # Create Flask app
    app = create_app(config_dir, root=getattr(args, "config_root", None))

    # Run server (single-threaded because PyDatabase is not thread-safe)
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        threaded=False
    )

    return 0
