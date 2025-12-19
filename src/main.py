#!/usr/bin/env python3
"""Voice Rewrite application entry point.

This module provides a unified entry point for all interfaces:
- GUI: Graphical interface with PySide6
- TUI: Terminal interface with Textual
- CLI: Command-line interface
- Web: RESTful HTTP API

Usage:
    python -m src.main                     # Use default interface from config (or GUI)
    python -m src.main --theme light       # Launch default interface with light theme
    python -m src.main gui                 # Launch GUI
    python -m src.main tui                 # Launch TUI
    python -m src.main cli list-notes      # Use CLI
    python -m src.main web [--port 8080]   # Start web server
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import NoReturn, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def add_gui_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add GUI subparser and its arguments.

    Args:
        subparsers: Parent subparsers object to add GUI parser to
    """
    gui_parser = subparsers.add_parser(
        "gui",
        help="Launch graphical interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    gui_parser.add_argument(
        "--theme",
        choices=["dark", "light"],
        default="dark",
        help="UI theme (default: dark)"
    )


def run_gui(config_dir: Optional[Path], args: argparse.Namespace) -> int:
    """Run GUI with given arguments.

    Args:
        config_dir: Custom configuration directory or None for default
        args: Parsed command-line arguments (should have theme attribute)

    Returns:
        Exit code from Qt application
    """
    from PySide6.QtWidgets import QApplication
    import qdarktheme

    from src.core.config import Config
    from src.core.database import Database
    from src.ui.main_window import MainWindow

    logger.info("Starting Voice Rewrite GUI")
    if config_dir:
        logger.info(f"Using custom config directory: {config_dir}")

    # Initialize config with custom directory if specified
    config = Config(config_dir=config_dir)

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
    theme = getattr(args, 'theme', 'dark')
    theme_stylesheet = qdarktheme.load_stylesheet(theme=theme)
    app.setStyleSheet(theme_stylesheet)

    # Create and show main window
    window = MainWindow(config, db, theme=theme)
    window.show()

    logger.info("Application window displayed")

    # Run event loop
    return app.exec()


def create_parser() -> argparse.ArgumentParser:
    """Create the unified argument parser.

    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        description="Voice Rewrite - Note-taking application with hierarchical tags",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main                     Use default interface (from config or GUI)
  python -m src.main gui --theme light   Launch GUI with light theme
  python -m src.main tui                 Launch terminal interface
  python -m src.main cli list-notes      List all notes via CLI
  python -m src.main cli search --tag Work
  python -m src.main web --port 8080     Start web server on port 8080
""",
    )

    parser.add_argument(
        "-d", "--config-dir",
        type=Path,
        default=None,
        help="Custom configuration directory (default: ~/.config/voicerewrite/)"
    )

    parser.add_argument(
        "--theme",
        choices=["dark", "light"],
        default="dark",
        help="UI theme for GUI (default: dark)"
    )

    # Create subparsers for each interface
    subparsers = parser.add_subparsers(dest="interface", help="Interface to use")

    # Add GUI subparser
    add_gui_subparser(subparsers)

    # Add TUI subparser (imports tui module)
    from src.tui import add_tui_subparser
    add_tui_subparser(subparsers)

    # Add CLI subparser (imports cli module)
    from src.cli import add_cli_subparser
    add_cli_subparser(subparsers)

    # Add Web subparser (imports web module)
    from src.web import add_web_subparser
    add_web_subparser(subparsers)

    return parser


def get_default_interface(config_dir: Optional[Path]) -> str:
    """Get default interface from config file.

    Args:
        config_dir: Custom configuration directory or None for default

    Returns:
        Interface name: "gui", "cli", or "web"
    """
    from src.core.config import Config
    config = Config(config_dir=config_dir)
    return config.get("default_interface", "gui")


def main() -> NoReturn:
    """Main entry point for Voice Rewrite.

    Parses arguments and dispatches to the appropriate interface.
    """
    parser = create_parser()
    args = parser.parse_args()

    # If no interface specified, use default from config
    if not args.interface:
        default_interface = get_default_interface(args.config_dir)
        logger.info(f"No interface specified, using default: {default_interface}")

        # Re-parse with default interface
        # We need to inject the default interface into argv
        new_argv = sys.argv[:]
        # Find where to insert the interface (after any global options)
        insert_pos = 1
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg in ["-d", "--config-dir"]:
                insert_pos = i + 2  # Skip the option and its value
            elif arg.startswith("-"):
                continue
            else:
                break

        new_argv.insert(insert_pos, default_interface)
        args = parser.parse_args(new_argv[1:])

    # Dispatch to appropriate interface
    if args.interface == "gui":
        exit_code = run_gui(args.config_dir, args)
    elif args.interface == "tui":
        from src.tui import run as run_tui
        exit_code = run_tui(args.config_dir, args)
    elif args.interface == "cli":
        from src.cli import run as run_cli
        exit_code = run_cli(args.config_dir, args)
    elif args.interface == "web":
        from src.web import run as run_web
        exit_code = run_web(args.config_dir, args)
    else:
        parser.print_help()
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
