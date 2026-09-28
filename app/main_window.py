"""
Main application window — sidebar + stacked panels + status bar.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget,
    QStatusBar, QLabel, QApplication,
)
from PySide6.QtCore import Qt

from .theme.theme_manager import ThemeManager, COLORS
from .widgets.sidebar import Sidebar
from .widgets.terminal import EmbeddedTerminal
from .panels.dashboard import DashboardPanel
from .panels.input_config import InputConfigPanel
from .panels.spectrum_panel import SpectrumPanel
from .panels.region_selector import RegionSelectorPanel
from .panels.calibration_panel import CalibrationPanel
from .panels.peak_editor import PeakEditorPanel
from .panels.fit_runner import FitRunnerPanel
from .panels.results_panel import ResultsPanel


class MainWindow(QMainWindow):
    """SpectraFlow main window with sidebar navigation and panel stack."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SpectraFlow — NMR Mixture Analysis")
        self.setMinimumSize(1000, 700)
        self.resize(1400, 900)

        # Theme
        self._theme = ThemeManager(self)

        # Build UI
        self._build_ui()
        self._connect_signals()

    # ── Build ───────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar()
        layout.addWidget(self._sidebar)

        # Stacked panels
        self._stack = QStackedWidget()

        # Create all panels
        self._panels: dict[str, QWidget] = {}

        self._dashboard = DashboardPanel()
        self._input_config = InputConfigPanel()
        self._spectrum = SpectrumPanel()
        self._regions = RegionSelectorPanel()
        self._calibration = CalibrationPanel()
        self._peaks = PeakEditorPanel()
        self._fit_runner = FitRunnerPanel()
        self._results = ResultsPanel()
        self._terminal_panel = self._make_terminal_panel()

        panel_map = [
            ("home", self._dashboard),
            ("input", self._input_config),
            ("viewer", self._spectrum),
            ("regions", self._regions),
            ("calibration", self._calibration),
            ("peaks", self._peaks),
            ("fit", self._fit_runner),
            ("results", self._results),
            ("terminal", self._terminal_panel),
        ]

        for name, widget in panel_map:
            self._panels[name] = widget
            self._stack.addWidget(widget)

        layout.addWidget(self._stack, stretch=1)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status_label = QLabel("Ready")
        self._status.addWidget(self._status_label, stretch=1)
        self._theme_indicator = QLabel("🌙 Dark")
        self._status.addPermanentWidget(self._theme_indicator)

    def _make_terminal_panel(self) -> QWidget:
        """Wrap the EmbeddedTerminal in a panel with padding."""
        wrapper = QWidget()
        wrapper.setObjectName("panel_content")
        lay = QHBoxLayout(wrapper)  # use QHBoxLayout for full width
        lay.setContentsMargins(16, 12, 16, 12)
        self._terminal = EmbeddedTerminal()
        self._terminal.command_submitted.connect(self._on_terminal_command)
        lay.addWidget(self._terminal)
        return wrapper

    # ── Connections ─────────────────────────────────────────
    def _connect_signals(self):
        # Sidebar navigation
        self._sidebar.navigation_changed.connect(self._navigate)

        # Theme toggle
        self._sidebar.theme_button.clicked.connect(self._toggle_theme)

        # Dashboard quick actions → navigate
        self._dashboard.action_requested.connect(self._navigate)

    def _navigate(self, name: str):
        """Switch to the panel identified by *name*."""
        if name in self._panels:
            self._stack.setCurrentWidget(self._panels[name])
            self._sidebar.set_active(name)
            self._status_label.setText(f"  {name.replace('_', ' ').title()}")

    # ── Theme ───────────────────────────────────────────────
    def _toggle_theme(self):
        app = QApplication.instance()
        new = self._theme.toggle_theme(app)
        is_dark = new == "dark"
        self._sidebar.set_theme_label(is_dark)
        self._theme_indicator.setText(f"{'🌙 Dark' if is_dark else '☀ Light'}")
        self._update_plot_themes()
        # Update Windows title bar color
        self._update_dwm_dark_mode(is_dark)

    def _update_plot_themes(self):
        """Push current color palette to all panels that have pyqtgraph plots."""
        colors = COLORS[self._theme.current_theme]
        for panel in self._panels.values():
            if hasattr(panel, "update_theme"):
                panel.update_theme(colors)

    def apply_initial_theme(self, app: QApplication, theme: str = "dark"):
        """Call once after show() to apply the starting theme."""
        self._theme.apply_theme(app, theme)
        self._sidebar.set_theme_label(theme == "dark")
        self._theme_indicator.setText(f"{'🌙 Dark' if theme == 'dark' else '☀ Light'}")
        self._update_plot_themes()

    def _update_dwm_dark_mode(self, dark: bool):
        """Update Windows title bar to match current theme."""
        import platform
        if platform.system() != "Windows":
            return
        try:
            import ctypes
            from ctypes import c_int, byref, sizeof
            hwnd = int(self.winId())
            val = c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, byref(val), sizeof(val)
            )
        except Exception:
            pass

    # ── Terminal ────────────────────────────────────────────
    def _on_terminal_command(self, cmd: str):
        """Handle typed commands in the embedded terminal."""
        parts = cmd.strip().split()
        if not parts:
            return
        command = parts[0].lower()

        if command == "help":
            self._terminal.write("Available commands:", "#4fc3f7")
            self._terminal.write("  help          — show this help")
            self._terminal.write("  theme [dark|light] — switch theme")
            self._terminal.write("  goto <panel>  — navigate to a panel")
            self._terminal.write("  clear         — clear terminal")
            self._terminal.write("  version       — show version info")
        elif command == "clear":
            self._terminal.clear()
        elif command == "version":
            from app import __version__
            self._terminal.write(f"SpectraFlow v{__version__}", "#4fc3f7")
        elif command == "theme":
            if len(parts) > 1 and parts[1] in ("dark", "light"):
                app = QApplication.instance()
                self._theme.apply_theme(app, parts[1])
                self._sidebar.set_theme_label(parts[1] == "dark")
                self._theme_indicator.setText(f"{'🌙 Dark' if parts[1] == 'dark' else '☀ Light'}")
                self._update_plot_themes()
                self._terminal.write_success(f"Theme set to {parts[1]}")
            else:
                self._terminal.write(f"Current: {self._theme.current_theme}")
        elif command == "goto":
            if len(parts) > 1:
                self._navigate(parts[1])
                self._terminal.write_success(f"Navigated to {parts[1]}")
            else:
                self._terminal.write("Usage: goto <panel_name>")
                self._terminal.write(f"  Panels: {', '.join(self._panels.keys())}")
        else:
            self._terminal.write_error(f"Unknown command: {command}")
