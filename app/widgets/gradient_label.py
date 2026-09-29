"""Label whose text is filled with a horizontal gradient.

Qt stylesheets cannot gradient-fill text (the CSS ``background-clip: text``
trick has no equivalent), so the text is painted directly with a gradient pen.
Font, size and weight still come from the stylesheet via the object name.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QLabel


class GradientLabel(QLabel):
    """QLabel that draws its text using a start -> end colour gradient."""

    def __init__(self, text: str = "", start: str = "#93c5fd", end: str = "#3b82f6", parent=None):
        super().__init__(text, parent)
        self._start = QColor(start)
        self._end = QColor(end)

    def set_colors(self, start: str, end: str) -> None:
        self._start = QColor(start)
        self._end = QColor(end)
        self.update()

    def paintEvent(self, event):
        text = self.text()
        if not text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())

        rect = self.contentsRect()
        flags = self.alignment().value
        if self.wordWrap():
            flags |= Qt.TextFlag.TextWordWrap.value

        bounds = painter.fontMetrics().boundingRect(rect, flags, text)
        gradient = QLinearGradient(bounds.left(), 0, max(bounds.right(), bounds.left() + 1), 0)
        gradient.setColorAt(0.0, self._start)
        gradient.setColorAt(1.0, self._end)

        painter.setPen(QPen(QBrush(gradient), 1))
        painter.drawText(rect, flags, text)
