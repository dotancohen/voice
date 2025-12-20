#!/usr/bin/env python3
"""Web API for Voice Rewrite.

This module provides a RESTful HTTP API for interacting with notes and tags.
Uses only core/ modules - no Qt/PySide6 dependencies.

Endpoints:
    GET  /api/notes              List all notes
    POST /api/notes              Create a new note
    GET  /api/notes/<id>         Get specific note
    PUT  /api/notes/<id>         Update a note
    GET  /api/tags               List all tags
    GET  /api/search             Search notes

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


def create_app(config_dir: Optional[Path] = None) -> Flask:
    """Create and configure Flask application.

    Args:
        config_dir: Custom configuration directory (default: None)

    Returns:
        Configured Flask application
    """
    app = Flask(__name__)
    CORS(app)  # Enable CORS for all routes

    # Initialize config and database
    config = Config(config_dir=config_dir)
    db_path_str = config.get("database_file")
    db_path = Path(db_path_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    global db
    db = Database(db_path)

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
    logger.info("Starting Voice Rewrite Web API")
    if config_dir:
        logger.info(f"Using custom config directory: {config_dir}")

    # Create Flask app
    app = create_app(config_dir=config_dir)

    # Run server
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug
    )

    return 0
