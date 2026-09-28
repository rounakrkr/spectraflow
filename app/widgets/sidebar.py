"""
Sidebar navigation widget for SpectraFlow.
Icon + label buttons, theme toggle at bottom.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QSizePolicy, QSpacerItem,
)
from PySide6.QtCore import Signal, Qt


class Sidebar(QWidget):
    """Vertical sidebar with icon-label navigation buttons."""

    navigation_changed = Signal(str)

    NAV_ITEMS = [
        ("home",        "🏠", "Dashboard"),
        ("input",       "📁", "Input Config"),
        ("viewer",      "📈", "Spectrum Viewer"),
        ("regions",     "🎯", "Region Selector"),
        ("calibration", "🎛", "Calibration"),
        ("peaks",       "✏", "Peak Editor"),
        ("fit",         "⚡", "Fit Runner"),
        ("results",     "📊", "Results"),
    ]

    BOTTOM_ITEMS = [
        ("terminal", "💻", "Terminal"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(220)
        self._buttons: dict[str, QPushButton] = {}
        self._theme_btn: QPushButton | None = None
        self._build_ui()

    # ── Build ───────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QWidget()
        header.setObjectName("sidebar_header")
        h_lay = QVBoxLayout(header)
        h_lay.setContentsMargins(16, 16, 16, 12)
        h_lay.setSpacing(2)

        logo = QLabel("⚛  SpectraFlow")
        logo.setObjectName("sidebar_logo")
        h_lay.addWidget(logo)

        from app import __version__
        ver = QLabel(f"v{__version__} — NMR Mixture Analysis")
        ver.setObjectName("sidebar_version")
        h_lay.addWidget(ver)

        root.addWidget(header)
        root.addSpacing(4)

        # Main nav
        for name, icon, label in self.NAV_ITEMS:
            root.addWidget(self._make_btn(name, icon, label))

        root.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: rgba(128,128,128,0.25);")
        root.addWidget(sep)
        root.addSpacing(4)

        # Bottom nav
        for name, icon, label in self.BOTTOM_ITEMS:
            root.addWidget(self._make_btn(name, icon, label))

        # Theme toggle
        self._theme_btn = QPushButton("🌙  Dark Theme")
        self._theme_btn.setObjectName("sidebar_theme_btn")
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(self._theme_btn)
        root.addSpacing(8)

        # Default active
        self.set_active("home")

    def _make_btn(self, name: str, icon: str, label: str) -> QPushButton:
        btn = QPushButton(f" {icon}   {label}")
        btn.setObjectName("sidebar_btn")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _checked, n=name: self._on_click(n))
        self._buttons[name] = btn
        return btn

    # ── Slots ───────────────────────────────────────────────
    def _on_click(self, name: str):
        self.set_active(name)
        self.navigation_changed.emit(name)

    def set_active(self, name: str):
        """Highlight *name* and un-check everything else."""
        for key, btn in self._buttons.items():
            btn.setChecked(key == name)

    @property
    def theme_button(self) -> QPushButton:
        """Expose the theme-toggle button so MainWindow can connect it."""
        return self._theme_btn

    def set_theme_label(self, is_dark: bool):
        """Update the theme button text to reflect current theme."""
        if is_dark:
            self._theme_btn.setText("🌙  Dark Theme")
        else:
            self._theme_btn.setText("☀  Light Theme")
