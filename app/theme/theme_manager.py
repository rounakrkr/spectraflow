"""
Theme Manager for SpectraFlow.
Handles dark/light theme switching with QSS stylesheets.
"""

from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal


class ThemeManager(QObject):
    """Manages application themes (dark/light) using Qt Style Sheets."""

    theme_changed = Signal(str)  # Emits "dark" or "light"

    THEME_DIR = Path(__file__).parent
    THEMES = {"dark": "dark.qss", "light": "light.qss"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_theme = "dark"  # Default

    @property
    def current_theme(self) -> str:
        return self._current_theme

    @property
    def is_dark(self) -> bool:
        return self._current_theme == "dark"

    def apply_theme(self, app: QApplication, theme_name: str = "dark") -> None:
        """Apply a theme to the entire application."""
        if theme_name not in self.THEMES:
            raise ValueError(f"Unknown theme: {theme_name}. Use: {list(self.THEMES.keys())}")

        qss_path = self.THEME_DIR / self.THEMES[theme_name]
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as f:
                stylesheet = f.read()
            app.setStyleSheet(stylesheet)
            self._current_theme = theme_name
            self.theme_changed.emit(theme_name)
        else:
            raise FileNotFoundError(f"Theme file not found: {qss_path}")

    def toggle_theme(self, app: QApplication) -> str:
        """Toggle between dark and light themes. Returns the new theme name."""
        new_theme = "light" if self._current_theme == "dark" else "dark"
        self.apply_theme(app, new_theme)
        return new_theme

    def get_color(self, name: str) -> str:
        """Get a named color for the current theme (for programmatic use)."""
        return COLORS[self._current_theme].get(name, "#ff00ff")


# Programmatic color access for widgets that need colors in code (e.g. pyqtgraph)
COLORS = {
    "dark": {
        "bg_primary": "#0b1626",
        "bg_secondary": "#10203a",
        "bg_card": "#10203a",
        "bg_input": "#10203a",
        "sidebar_bg": "#08111f",
        "sidebar_hover": "#132844",
        "sidebar_active": "#2563eb",
        "accent": "#60a5fa",
        "accent_hover": "#93c5fd",
        "accent_dark": "#3b82f6",
        "success": "#34d399",
        "warning": "#fbbf24",
        "error": "#f87171",
        "text_primary": "#e4e8ee",
        "text_secondary": "#8ea2c0",
        "text_muted": "#6b7f9e",
        "border": "rgba(255, 255, 255, 0.1)",
        "border_light": "rgba(255, 255, 255, 0.15)",
        "plot_bg": "#0a1424",
        "plot_fg": "#e4e8ee",
        "plot_grid": "rgba(255, 255, 255, 0.06)",
        "plot_line": "#60a5fa",
        "plot_line_alt": "#f472b6",
        "plot_region": "#3b82f633",
        "grad_start": "#dbeafe",
        "grad_end": "#60a5fa",
    },
    "light": {
        "bg_primary": "#f8f9fc",
        "bg_secondary": "#ffffff",
        "bg_card": "#ffffff",
        "bg_input": "#f0f2f5",
        "sidebar_bg": "#f0f2f5",
        "sidebar_hover": "#e4e8ee",
        "sidebar_active": "#d6e4f0",
        "accent": "#1976d2",
        "accent_hover": "#1565c0",
        "accent_dark": "#0d47a1",
        "success": "#2e7d32",
        "warning": "#f57f17",
        "error": "#c62828",
        "text_primary": "#1a1f2e",
        "text_secondary": "#5c6370",
        "text_muted": "#8892a0",
        "border": "#dde1e6",
        "border_light": "#e8ecf0",
        "plot_bg": "#ffffff",
        "plot_fg": "#1a1f2e",
        "plot_grid": "#e0e0e0",
        "plot_line": "#1976d2",
        "plot_line_alt": "#e64a19",
        "plot_region": "#1976d233",
        "grad_start": "#1d4ed8",
        "grad_end": "#6d28d9",
    },
}
