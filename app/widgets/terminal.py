"""
Embedded terminal / console widget.
Read-only output area + single-line command input.
"""

import sys
from datetime import datetime

from app import __version__
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QLineEdit, QHBoxLayout, QLabel,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QTextCursor, QColor, QFont


class EmbeddedTerminal(QWidget):
    """Mini terminal with colored output and command input line."""

    command_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._hist_idx = -1
        self._build_ui()

    # ── Build ───────────────────────────────────────────────
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Output
        self._output = QTextEdit()
        self._output.setObjectName("terminal_output")
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Cascadia Code", 11))
        lay.addWidget(self._output)

        # Input row
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self._prompt = QLabel(" ❯ ")
        self._prompt.setObjectName("terminal_input")
        self._prompt.setFixedWidth(32)
        self._prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._prompt)

        self._input = QLineEdit()
        self._input.setObjectName("terminal_input")
        self._input.setPlaceholderText("Type a command…")
        self._input.returnPressed.connect(self._on_submit)
        row.addWidget(self._input)

        lay.addLayout(row)

        # Welcome message
        self.write(f"SpectraFlow Terminal v{__version__}", "#4fc3f7")
        self.write(f"Session started at {datetime.now():%Y-%m-%d %H:%M:%S}", "#8892a0")
        self.write("Type 'help' for available commands.\n", "#8892a0")

    # ── Input handling ──────────────────────────────────────
    def _on_submit(self):
        text = self._input.text().strip()
        if not text:
            return
        self._history.append(text)
        self._hist_idx = len(self._history)
        self.write(f"❯ {text}", "#4fc3f7")
        self._input.clear()
        self.command_submitted.emit(text)

    def keyPressEvent(self, event):
        """Up/Down arrow for history navigation."""
        if event.key() == Qt.Key.Key_Up and self._history:
            self._hist_idx = max(0, self._hist_idx - 1)
            self._input.setText(self._history[self._hist_idx])
        elif event.key() == Qt.Key.Key_Down and self._history:
            self._hist_idx = min(len(self._history), self._hist_idx + 1)
            if self._hist_idx < len(self._history):
                self._input.setText(self._history[self._hist_idx])
            else:
                self._input.clear()
        else:
            super().keyPressEvent(event)

    # ── Public API ──────────────────────────────────────────
    def write(self, text: str, color: str | None = None):
        """Append a line to the output area."""
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if color:
            self._output.setTextCursor(cursor)
            self._output.setTextColor(QColor(color))
        else:
            self._output.setTextCursor(cursor)
            self._output.setTextColor(QColor("#c8d0da"))
        self._output.append(text)
        # Auto-scroll
        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def write_error(self, text: str):
        self.write(f"✗ {text}", "#ef5350")

    def write_success(self, text: str):
        self.write(f"✓ {text}", "#66bb6a")

    def write_warning(self, text: str):
        self.write(f"⚠ {text}", "#ffa726")

    def clear(self):
        self._output.clear()
