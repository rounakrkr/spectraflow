"""
File / folder browser widget.
Layout:  [Label]  [path display (read-only)]  [Browse]
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QListWidget,
    QListWidgetItem, QAbstractItemView,
)
from PySide6.QtCore import Signal, Qt


class FileBrowser(QWidget):
    """Single-file, multi-file, or directory browser with path display."""

    path_changed = Signal(str)

    def __init__(
        self,
        label: str = "File",
        mode: str = "file",          # "file" | "files" | "directory"
        file_filter: str = "",       # e.g. "NMR Files (*.fid *.fvf);;All (*)"
        placeholder: str = "No file selected",
        parent=None,
    ):
        super().__init__(parent)
        self._mode = mode
        self._filter = file_filter
        self._paths: list[str] = []
        self._build_ui(label, placeholder)

    # ── Build ───────────────────────────────────────────────
    def _build_ui(self, label: str, placeholder: str):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        if label:
            lbl = QLabel(label)
            lbl.setObjectName("section_title")
            outer.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(6)

        self._path_edit = QLineEdit()
        self._path_edit.setObjectName("path_display")
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText(placeholder)
        row.addWidget(self._path_edit, stretch=1)

        browse = QPushButton("Browse…")
        browse.setFixedWidth(90)
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)

        outer.addLayout(row)

        # Multi-file mode: show a list below
        if self._mode == "files":
            self._list = QListWidget()
            self._list.setMaximumHeight(120)
            self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            outer.addWidget(self._list)

    # ── Browse ──────────────────────────────────────────────
    def _browse(self):
        if self._mode == "file":
            path, _ = QFileDialog.getOpenFileName(self, "Select File", "", self._filter)
            if path:
                self._paths = [path]
                self._path_edit.setText(path)
                self.path_changed.emit(path)

        elif self._mode == "files":
            paths, _ = QFileDialog.getOpenFileNames(self, "Select Files", "", self._filter)
            if paths:
                self._paths = paths
                self._path_edit.setText(f"{len(paths)} files selected")
                self._list.clear()
                for p in paths:
                    self._list.addItem(QListWidgetItem(p))
                self.path_changed.emit(";".join(paths))

        elif self._mode == "directory":
            path = QFileDialog.getExistingDirectory(self, "Select Directory")
            if path:
                self._paths = [path]
                self._path_edit.setText(path)
                self.path_changed.emit(path)

    # ── Public API ──────────────────────────────────────────
    def get_path(self) -> str:
        return self._paths[0] if self._paths else ""

    def get_paths(self) -> list[str]:
        return list(self._paths)

    def set_path(self, path: str):
        self._paths = [path]
        self._path_edit.setText(path)
