"""Shared UI styles for PySide6 widgets.

This module contains style definitions shared across multiple UI components.
"""

# Button focus style - makes focused buttons visually distinct
BUTTON_STYLE = """
    QPushButton {
        padding: 5px 15px;
    }
    QPushButton:focus {
        border: 2px solid #3daee9;
        background-color: #3daee9;
        color: white;
    }
"""
