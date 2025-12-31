"""Transcription dialog for PySide6 GUI.

This module provides a dialog for configuring and starting transcription
of audio files with multiple providers.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.ui.styles import BUTTON_STYLE

logger = logging.getLogger(__name__)


# Common language codes for dropdown
COMMON_LANGUAGES = [
    ("", "Auto-detect"),
    ("en", "English"),
    ("he", "Hebrew"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ar", "Arabic"),
]


class ProviderOptionsWidget(QWidget):
    """Widget for displaying provider-specific options."""

    def __init__(
        self,
        provider_schema: Any,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize provider options widget.

        Args:
            provider_schema: ProviderSchema object from voice_transcription
            parent: Parent widget
        """
        super().__init__(parent)
        self._schema = provider_schema
        self._option_widgets: Dict[str, QWidget] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        for option in self._schema.options:
            widget = self._create_option_widget(option)
            self._option_widgets[option.id] = widget
            layout.addRow(option.label + ":", widget)

            if option.description:
                desc_label = QLabel(option.description)
                desc_label.setStyleSheet("color: gray; font-size: 10px;")
                desc_label.setWordWrap(True)
                layout.addRow("", desc_label)

    def _create_option_widget(self, option: Any) -> QWidget:
        """Create widget for an option based on its type.

        Args:
            option: ProviderOption object

        Returns:
            Appropriate input widget
        """
        if option.option_type == "select":
            combo = QComboBox()
            for value in option.values:
                combo.addItem(value.label, value.value)
            if option.default:
                index = combo.findData(option.default)
                if index >= 0:
                    combo.setCurrentIndex(index)
            return combo

        elif option.option_type == "checkbox":
            checkbox = QCheckBox()
            checkbox.setChecked(option.default.lower() == "true")
            return checkbox

        elif option.option_type == "number":
            spinbox = QSpinBox()
            spinbox.setRange(0, 10000)
            if option.default:
                try:
                    spinbox.setValue(int(option.default))
                except ValueError:
                    pass
            return spinbox

        elif option.option_type == "path":
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            line_edit = QLineEdit()
            line_edit.setPlaceholderText("Optional: path to custom model file")
            browse_btn = QPushButton("Browse...")
            browse_btn.setStyleSheet(BUTTON_STYLE)
            layout.addWidget(line_edit, 1)
            layout.addWidget(browse_btn)
            # Store the line edit for value retrieval
            widget.line_edit = line_edit
            return widget

        else:  # text or default
            line_edit = QLineEdit()
            if option.default:
                line_edit.setText(option.default)
            return line_edit

    def get_values(self) -> Dict[str, Any]:
        """Get current option values.

        Returns:
            Dict mapping option IDs to their values
        """
        values = {}
        for option in self._schema.options:
            widget = self._option_widgets.get(option.id)
            if widget is None:
                continue

            if option.option_type == "select":
                values[option.id] = widget.currentData()
            elif option.option_type == "checkbox":
                values[option.id] = widget.isChecked()
            elif option.option_type == "number":
                values[option.id] = widget.value()
            elif option.option_type == "path":
                values[option.id] = widget.line_edit.text()
            else:
                values[option.id] = widget.text()

        return values


class TranscriptionDialog(QDialog):
    """Dialog for configuring and starting transcription."""

    def __init__(
        self,
        audio_filename: str,
        provider_schemas: List[Any],
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize transcription dialog.

        Args:
            audio_filename: Name of audio file being transcribed
            provider_schemas: List of ProviderSchema objects
            parent: Parent widget
        """
        super().__init__(parent)
        self._audio_filename = audio_filename
        self._provider_schemas = provider_schemas
        self._provider_checkboxes: Dict[str, QCheckBox] = {}
        self._provider_options: Dict[str, ProviderOptionsWidget] = {}
        self._result_configs: List[Dict[str, Any]] = []

        self.setWindowTitle("Transcribe Audio")
        self.setMinimumWidth(450)
        self.setMinimumHeight(400)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        # File info
        file_label = QLabel(f"Transcribing: {self._audio_filename}")
        file_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(file_label)

        # Scroll area for providers
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # Provider selection
        providers_group = QGroupBox("Providers")
        providers_layout = QVBoxLayout(providers_group)

        for schema in self._provider_schemas:
            # Checkbox for provider
            checkbox = QCheckBox(schema.provider_name)
            checkbox.setChecked(True)  # Default to checked
            self._provider_checkboxes[schema.provider_id] = checkbox

            # Options widget
            options_widget = ProviderOptionsWidget(schema)
            self._provider_options[schema.provider_id] = options_widget

            # Connect checkbox to show/hide options
            checkbox.toggled.connect(
                lambda checked, w=options_widget: w.setVisible(checked)
            )

            providers_layout.addWidget(checkbox)
            providers_layout.addWidget(options_widget)

        scroll_layout.addWidget(providers_group)

        # Common options
        common_group = QGroupBox("Common Options")
        common_layout = QFormLayout(common_group)

        # Language
        self._language_combo = QComboBox()
        for code, name in COMMON_LANGUAGES:
            self._language_combo.addItem(name, code)
        common_layout.addRow("Language:", self._language_combo)

        # Speaker count
        self._speaker_spinbox = QSpinBox()
        self._speaker_spinbox.setRange(0, 10)
        self._speaker_spinbox.setValue(0)
        self._speaker_spinbox.setSpecialValueText("Auto")
        common_layout.addRow("Speakers:", self._speaker_spinbox)

        scroll_layout.addWidget(common_group)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(BUTTON_STYLE)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        transcribe_btn = QPushButton("Transcribe")
        transcribe_btn.setStyleSheet(BUTTON_STYLE)
        transcribe_btn.setDefault(True)
        transcribe_btn.clicked.connect(self._on_transcribe)
        button_layout.addWidget(transcribe_btn)

        layout.addLayout(button_layout)

    def _on_transcribe(self) -> None:
        """Handle transcribe button click."""
        self._result_configs = []

        # Get common options
        language = self._language_combo.currentData() or None
        speaker_count = self._speaker_spinbox.value() or None

        # Build config for each selected provider
        for provider_id, checkbox in self._provider_checkboxes.items():
            if not checkbox.isChecked():
                continue

            options = self._provider_options[provider_id].get_values()

            config = {
                "provider_id": provider_id,
                "language": language,
                "speaker_count": speaker_count,
                **options,
            }
            self._result_configs.append(config)

        if not self._result_configs:
            # No providers selected
            return

        self.accept()

    def get_provider_configs(self) -> List[Dict[str, Any]]:
        """Get the configured provider configs after dialog is accepted.

        Returns:
            List of provider config dicts, one per selected provider
        """
        return self._result_configs
