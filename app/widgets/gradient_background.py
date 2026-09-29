"""Painted gradient backdrop for the main window.

Qt stylesheets can only paint a single background per widget, so the layered
"mesh" look (a base gradient plus several soft radial glows) is drawn here and
cached as a pixmap. Every widget above it is transparent, which is what lets the
translucent glass cards pick up the glow behind them.
"""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget


class GradientBackground(QWidget):
    """Full-window backdrop: vertical base gradient plus radial colour glows."""

    # Each glow: (x fraction, y fraction, radius as a fraction of the longer side, colour, alpha)
    PALETTES = {
        "dark": {
            "top": "#0b1a33",
            "bottom": "#060d1a",
            "glows": [
                (0.10, 0.02, 0.80, "#2563eb", 0.30),
                (0.98, 0.95, 0.70, "#6d28d9", 0.16),
                (0.85, 0.05, 0.45, "#06b6d4", 0.09),
            ],
        },
        "light": {
            "top": "#f6f9ff",
            "bottom": "#e6eefb",
            "glows": [
                (0.10, 0.02, 0.80, "#3b82f6", 0.18),
                (0.98, 0.95, 0.70, "#a78bfa", 0.14),
            ],
        },
    }

    def __init__(self, theme: str = "dark", parent=None):
        super().__init__(parent)
        self._theme = theme if theme in self.PALETTES else "dark"
        self._cache = QPixmap()
        self._glass = False
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    # Fraction of the gradient's opacity kept when a Mica/Acrylic backdrop is active,
    # so the system material can show through the tint.
    GLASS_OPACITY = 0.72

    def set_glass(self, enabled: bool) -> None:
        """Let a system backdrop (Mica/Acrylic) show through instead of painting opaque."""
        if enabled != self._glass:
            self._glass = enabled
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, not enabled)
            self.update()

    @property
    def theme(self) -> str:
        return self._theme

    def set_theme(self, theme: str) -> None:
        """Switch palette ('dark' or 'light'); unknown names are ignored."""
        if theme in self.PALETTES and theme != self._theme:
            self._theme = theme
            self._cache = QPixmap()
            self.update()

    def resizeEvent(self, event):
        self._cache = QPixmap()
        super().resizeEvent(event)

    def _render(self) -> None:
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0:
            return
        dpr = self.devicePixelRatioF()
        pixmap = QPixmap(int(width * dpr), int(height * dpr))
        pixmap.setDevicePixelRatio(dpr)

        palette = self.PALETTES[self._theme]
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        base = QLinearGradient(0, 0, 0, height)
        base.setColorAt(0.0, QColor(palette["top"]))
        base.setColorAt(1.0, QColor(palette["bottom"]))
        painter.fillRect(0, 0, width, height, QBrush(base))

        span = max(width, height)
        for cx, cy, radius, colour, alpha in palette["glows"]:
            centre = QColor(colour)
            centre.setAlphaF(alpha)
            edge = QColor(colour)
            edge.setAlpha(0)
            glow = QRadialGradient(QPointF(cx * width, cy * height), radius * span)
            glow.setColorAt(0.0, centre)
            glow.setColorAt(1.0, edge)
            painter.fillRect(0, 0, width, height, QBrush(glow))

        painter.end()
        self._cache = pixmap

    def paintEvent(self, event):
        if self._cache.isNull():
            self._render()
        if self._cache.isNull():
            return
        painter = QPainter(self)
        if self._glass:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setOpacity(self.GLASS_OPACITY)
        painter.drawPixmap(0, 0, self._cache)
