"""The Issues window (ISSUE-1): what needs the user's attention, read afresh
each time it opens or is refreshed. Nothing here nags: it is opened from the
File menu, and it only lists."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from src.core.issues_text import issue_sections, place_names


class IssuesDialog(QDialog):
    def __init__(self, db, config, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.setWindowTitle("Issues")
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree)
        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(refresh)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.reload()

    def reload(self) -> None:
        issues = self.db.issues(self.config.get_audiofile_directory())
        sections = issue_sections(issues, place_names(self.db, self.config))
        self.tree.clear()
        for title, lines in sections:
            top = QTreeWidgetItem([title])
            for line in lines:
                top.addChild(QTreeWidgetItem([line]))
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.summary.setText("Nothing needs your attention." if not sections else f"{issues['count']} things need your attention.")
