"""The light or dark look of the desktop GUI.

qdarktheme's stylesheet colours the widgets, and its palette gives the same
colours to whatever the program draws itself (the copy icon, for one). With the
stylesheet alone the palette stays the system's, so an icon drawn from it had
dark ink on the dark theme's dark window.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication, theme: str) -> None:
    """Give the application the stylesheet and the palette of `theme` ("dark" or "light")."""
    import qdarktheme

    app.setStyleSheet(qdarktheme.load_stylesheet(theme=theme))
    app.setPalette(qdarktheme.load_palette(theme=theme))
