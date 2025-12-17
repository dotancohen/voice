#!/usr/bin/env python3
"""Voice Rewrite application entry point.

This module initializes the application, loads configuration,
sets up the database, and launches the main window.

Command-line arguments:
    -d, --config-dir PATH    Specify custom configuration directory
    --theme {dark,light}     UI theme (default: dark)
    --<component>=<impl>     Select implementation for pluggable components (future)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import NoReturn

from PySide6.QtWidgets import QApplication
import qdarktheme

from core.config import Config
from core.database import Database
from ui.main_window import MainWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Voice Rewrite - Note-taking application with hierarchical tags",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-d",
        "--config-dir",
        type=Path,
        default=None,
        help="Custom configuration directory (default: ~/.config/voicerewrite/)",
    )

    parser.add_argument(
        "--theme",
        choices=["dark", "light"],
        default="dark",
        help="UI theme (default: dark)",
    )

    # Future: Add implementation selection arguments
    # parser.add_argument('--player', choices=['vlc', 'mpv'], help='Media player implementation')
    # parser.add_argument('--waveform', choices=['matplotlib', 'pyqtgraph'],
    #                     help='Waveform implementation')

    return parser.parse_args()


def main() -> NoReturn:
    """Initialize and run the Voice Rewrite application.

    Parses CLI arguments, initializes configuration and database,
    then launches the GUI.

    Exits:
        Exits with application return code.
    """
    # Parse command-line arguments
    args = parse_arguments()

    logger.info("Starting Voice Rewrite application")
    if args.config_dir:
        logger.info(f"Using custom config directory: {args.config_dir}")

    # Initialize config with custom directory if specified
    config = Config(config_dir=args.config_dir)

    # Initialize database
    db_path_str = config.get("database_file")
    db_path = Path(db_path_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)

    logger.info(f"Database location: {db_path}")

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("Voice Rewrite")

    # Close database on application exit
    app.aboutToQuit.connect(db.close)

    # Apply theme using qdarktheme
    theme_stylesheet = qdarktheme.load_stylesheet(theme=args.theme)
    app.setStyleSheet(theme_stylesheet)

    # Create and show main window
    window = MainWindow(config, db, theme=args.theme)
    window.show()

    logger.info("Application window displayed")

    # Run event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
