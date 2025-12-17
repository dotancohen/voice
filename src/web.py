#!/usr/bin/env python3
"""Web API for Voice Rewrite.

This module provides a RESTful HTTP API for interacting with notes and tags.
Uses only core/ modules - no Qt/PySide6 dependencies.

Endpoints:
    GET  /api/notes              List all notes
    GET  /api/notes/<id>         Get specific note
    GET  /api/tags               List all tags
    GET  /api/search             Search notes

All endpoints return JSON responses.

Query parameters for /api/search:
    - text: Text to search for in note content
    - tag: Tag path to filter by (can be specified multiple times for AND logic)
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional

from flask import Flask, jsonify, request, Response
from flask_cors import CORS

from src.core.config import Config
from src.core.database import Database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global database instance
db: Optional[Database] = None


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

    # Routes
    @app.route("/api/notes", methods=["GET"])
    def get_notes() -> Response:
        """Get all notes.

        Returns:
            JSON response with list of notes
        """
        try:
            notes = db.get_all_notes()
            return jsonify(notes)
        except Exception as e:
            logger.error(f"Error getting notes: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/notes/<int:note_id>", methods=["GET"])
    def get_note(note_id: int) -> tuple[Response, int]:
        """Get specific note by ID.

        Args:
            note_id: Note ID from URL path

        Returns:
            JSON response with note data or error
        """
        try:
            note = db.get_note(note_id)
            if note:
                return jsonify(note), 200
            else:
                return jsonify({"error": f"Note {note_id} not found"}), 404
        except Exception as e:
            logger.error(f"Error getting note {note_id}: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/tags", methods=["GET"])
    def get_tags() -> Response:
        """Get all tags.

        Returns:
            JSON response with list of tags
        """
        try:
            tags = db.get_all_tags()
            return jsonify(tags)
        except Exception as e:
            logger.error(f"Error getting tags: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/search", methods=["GET"])
    def search_notes() -> tuple[Response, int]:
        """Search notes by text and/or tags.

        Query parameters:
            text: Text to search for (optional)
            tag: Tag path to filter by (can specify multiple, AND logic)
                 Ambiguous tags (matching multiple tags) use OR logic within the group

        Returns:
            JSON response with matching notes
        """
        try:
            # Get query parameters
            text_query = request.args.get("text")
            tag_paths = request.args.getlist("tag")  # Get all 'tag' parameters

            # Build tag_id_groups
            # For ambiguous tags, all matching tags' descendants go into ONE group (OR logic)
            tag_id_groups: List[List[int]] = []
            any_tag_not_found = False

            for tag_path in tag_paths:
                # Get ALL tags matching this path
                matching_tags = db.get_all_tags_by_path(tag_path)

                if matching_tags:
                    # Collect all descendants from all matching tags into ONE group (OR logic)
                    all_descendants: List[int] = []
                    for tag in matching_tags:
                        descendants = db.get_tag_descendants(tag["id"])
                        all_descendants.extend(descendants)

                    # Remove duplicates
                    all_descendants = list(set(all_descendants))
                    tag_id_groups.append(all_descendants)

                    # Log if ambiguous (multiple matches)
                    if len(matching_tags) > 1:
                        logger.info(f"Tag '{tag_path}' is ambiguous - matching {len(matching_tags)} tags (using OR logic)")
                else:
                    logger.warning(f"Tag path '{tag_path}' not found")
                    any_tag_not_found = True

            # If any requested tag was not found, return empty results
            if any_tag_not_found:
                notes = []
            else:
                # Perform search
                notes = db.search_notes(
                    text_query=text_query if text_query else None,
                    tag_id_groups=tag_id_groups if tag_id_groups else None
                )

            return jsonify(notes), 200
        except Exception as e:
            logger.error(f"Error searching notes: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/health", methods=["GET"])
    def health_check() -> tuple[Response, int]:
        """Health check endpoint.

        Returns:
            JSON response indicating service health
        """
        return jsonify({"status": "ok"}), 200

    return app


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Voice Rewrite - Web API server",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "-d", "--config-dir",
        type=Path,
        default=None,
        help="Custom configuration directory (default: ~/.config/voicerewrite/)"
    )

    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to bind to (default: 5000)"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )

    return parser.parse_args()


def main() -> NoReturn:
    """Main web API entry point.

    Exits:
        Exits with application return code
    """
    args = parse_arguments()

    logger.info("Starting Voice Rewrite Web API")
    if args.config_dir:
        logger.info(f"Using custom config directory: {args.config_dir}")

    # Create Flask app
    app = create_app(config_dir=args.config_dir)

    # Run server
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug
    )


if __name__ == "__main__":
    main()
