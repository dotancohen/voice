#!/usr/bin/env python3
"""Voice application entry point.

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
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import NoReturn, Optional

# How large the log may grow before it is rotated, and how many old ones are
# kept. Bounded on purpose: see setup_file_logging.
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_FILES_KEPT = 2

# Configure console logging (file logging added later when config dir is known)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def setup_file_logging(config_dir: Path) -> None:
    """Add file handler to root logger.

    Args:
        config_dir: Configuration directory where voice.log will be created
    """
    log_file = config_dir / "voice.log"
    # Rotating, not plain: a sync server runs for months, and a log file that
    # only ever grows fills the disk and then cannot be read into a window to
    # look at. Five megabytes is weeks of ordinary use, and two old files are
    # kept behind it.
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_FILES_KEPT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logging.getLogger().addHandler(file_handler)
    logger.info(f"File logging enabled: {log_file}")


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

    logger.info("Starting Voice GUI")
    if config_dir:
        logger.info(f"Using custom config directory: {config_dir}")

    # The account's directory, under the machine's root
    config = Config(config_dir=config_dir, root=getattr(args, "config_root", None))

    # Initialize database
    db_path_str = config.get("database_file")
    db_path = Path(db_path_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    from src.core.synced_settings import reconcile_transcription_settings
    reconcile_transcription_settings(config, db)

    logger.info(f"Database location: {db_path}")

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("Voice")

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
        description="Voice - Note-taking application with hierarchical tags",
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
        "-a", "--account",
        dest="account",
        default=None,
        help="The account to open, by its id (or a unique prefix) or its label (default: $VOICE_ACCOUNT_ID, else the default account)"
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


def get_default_interface(config_dir: Optional[Path], root: Optional[Path] = None) -> str:
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
    config = Config(config_dir=config_dir, root=root)

    # Check if user has explicitly set a default interface
    configured = config.get("default_interface")
    if configured:
        return configured

    # Auto-detect: GUI if available, otherwise TUI
    if is_gui_available():
        return "gui"
    return "tui"


# The 'account' subcommands that read or write the index and open no account
INDEX_COMMANDS = ("list", "create", "default", "remove", "host")


def main() -> NoReturn:
    """Main entry point for Voice.

    Parses arguments and dispatches to the appropriate interface.
    """
    parser = create_parser()
    args = parser.parse_args()

    # The root: $VOICE_CONFIG_DIR, else ~/.config/voice. The account: -a, else
    # $VOICE_ACCOUNT_ID, else the default account (ACCT-6). A root that holds
    # one database and no index is the account itself.
    root = Path(os.environ["VOICE_CONFIG_DIR"]).expanduser() if os.environ.get("VOICE_CONFIG_DIR") else Path.home() / ".config" / "voice"
    selector = args.account or os.environ.get("VOICE_ACCOUNT_ID") or None
    # The commands that work on the index, and the listener, need no account
    # of their own: they never create the default account, and run without
    # one on a root that has none (Stage 3). Everything else opens an
    # account, making the default one first if the root is empty.
    serving = getattr(args, "interface", None) == "cli" and (
        (getattr(args, "cli_command", None) == "sync" and getattr(args, "sync_command", None) == "serve")
        or (getattr(args, "cli_command", None) == "account" and getattr(args, "account_command", None) in INDEX_COMMANDS)
    )
    from voicecore import resolve_account
    try:
        resolved = resolve_account(str(root), selector, not serving)
    except Exception as e:  # noqa: BLE001 - the sentence is the answer
        if not (serving and selector is None):
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        resolved = None
    machine_output = getattr(args, "format", "text") in ("json", "csv")
    from src.core.config import Config
    if resolved is None:
        args.config_dir = None
        args.config_root = root
        args.account_label = None
        root.mkdir(parents=True, exist_ok=True)
        setup_file_logging(root)
        print(f"Using CONFIG_DIR: {root} (no account of its own)", file=sys.stderr if machine_output else sys.stdout, flush=True)
    else:
        args.config_dir = Path(resolved["directory"])
        args.config_root = Path(resolved["root"])
        args.account_label = resolved.get("label")

        # Set up file logging early (for all interfaces)
        config = Config(config_dir=args.config_dir, root=args.config_root)
        setup_file_logging(config.get_config_dir())
        # This installation's key for its account, and its own device card,
        # made once and kept up to date with the device name (AUTH-1)
        from voicecore import ensure_own_device_card
        ensure_own_device_card(str(config.get_config_dir()))

        # Always say which configuration is in use, as the first line. Machine
        # formats keep stdout clean, so the line goes to stderr there.
        banner = f"Using CONFIG_DIR: {config.get_config_dir()}"
        if args.account_label:
            banner += f" (account {args.account_label})"
        print(banner, file=sys.stderr if machine_output else sys.stdout, flush=True)

    # If no interface specified, use default from config
    if not args.interface:
        default_interface = get_default_interface(args.config_dir, args.config_root)
        logger.info(f"No interface specified, using default: {default_interface}")

        # Re-parse with default interface
        # We need to inject the default interface into argv
        new_argv = sys.argv[:]
        # Find where to insert the interface (after any global options)
        insert_pos = 1
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg in ["-a", "--account"]:
                insert_pos = i + 2  # Skip the option and its value
            elif arg.startswith("-"):
                continue
            else:
                break

        new_argv.insert(insert_pos, default_interface)
        reparsed = parser.parse_args(new_argv[1:])
        # The second parse makes new arguments: carry over everything startup
        # has already worked out (the account's directory, root and label),
        # or the interface starts without its account
        for name, value in vars(args).items():
            if not hasattr(reparsed, name):
                setattr(reparsed, name, value)
        args = reparsed

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
