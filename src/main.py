#!/usr/bin/env python3
"""Voice Rewrite application entry point.

This module provides a unified entry point for all interfaces:
- GUI: Graphical interface with PySide6
- TUI: Terminal interface with Textual
- CLI: Command-line interface
- Web: RESTful HTTP API

Usage:
    python -m src.main                     # Auto-detect: GUI if available, else TUI
    python -m src.main --theme dark        # Launch with dark theme (overrides OS detection)
    python -m src.main gui                 # Launch GUI (theme detected from OS)
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
        default=None,
        help="UI theme (default: detect from OS)"
    )


def run_gui(config_dir: Optional[Path], args: argparse.Namespace) -> int:
    """Run GUI with given arguments.

    Args:
        config_dir: Custom configuration directory or None for default
        args: Parsed command-line arguments (should have theme attribute)

    Returns:
        Exit code from Qt application
    """
    try:
        from PySide6.QtWidgets import QApplication
        import qdarktheme
    except ImportError as e:
        missing = "PySide6" if "PySide6" in str(e) else "qdarktheme"
        print(f"Error: GUI dependencies not installed ({missing}).", file=sys.stderr)
        print(file=sys.stderr)
        print("To use the GUI, install the full requirements:", file=sys.stderr)
        print("    pip install -r requirements.txt", file=sys.stderr)
        print(file=sys.stderr)
        print("Or use the TUI instead:", file=sys.stderr)
        print("    python -m src.main tui", file=sys.stderr)
        return 1

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

    # Detect theme from OS if not specified
    theme = getattr(args, 'theme', None)
    if theme is None:
        from PySide6.QtCore import Qt
        try:
            # Qt 6.5+ has colorScheme()
            color_scheme = app.styleHints().colorScheme()
            theme = "dark" if color_scheme == Qt.ColorScheme.Dark else "light"
            logger.info(f"Detected OS theme: {theme}")
        except AttributeError:
            # Fallback for older Qt: check palette brightness
            palette = app.palette()
            bg_color = palette.window().color()
            is_dark = bg_color.lightness() < 128
            theme = "dark" if is_dark else "light"
            logger.info(f"Detected theme from palette: {theme}")

    # Apply theme using qdarktheme
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
  python -m src.main                     Auto-detect interface (GUI if available, else TUI)
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
        default=None,
        help="UI theme for GUI (default: detect from OS)"
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


def is_gui_available() -> bool:
    """Check if GUI dependencies (PySide6, qdarktheme) are available.

    Returns:
        True if GUI can be used, False otherwise.
    """
    try:
        import PySide6.QtWidgets  # noqa: F401
        import qdarktheme  # noqa: F401
        return True
    except ImportError:
        return False


def get_default_interface(config_dir: Optional[Path]) -> str:
    """Get default interface from config file, or detect based on available dependencies.

    Priority:
    1. Explicit setting in config file
    2. GUI if PySide6/qdarktheme are installed
    3. TUI otherwise

    Args:
        config_dir: Custom configuration directory or None for default

    Returns:
        Interface name: "gui", "tui", "cli", or "web"
    """
    from src.core.config import Config
    config = Config(config_dir=config_dir)

    # Check if user has explicitly set a default interface
    configured = config.get("default_interface")
    if configured:
        return configured

    # Auto-detect: GUI if available, otherwise TUI
    if is_gui_available():
        return "gui"
    return "tui"


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
