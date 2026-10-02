"""
Main application window — sidebar + stacked panels + status bar.
"""

import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget,
    QStatusBar, QLabel, QApplication, QMessageBox,
)

from .theme.theme_manager import ThemeManager, COLORS
from .core import exporter
from .core.engine import AnalysisEngine
from .widgets.gradient_background import GradientBackground
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

        # Backend engine
        self._engine = AnalysisEngine(self)
        self._analysis_traces: list[str] = []   # spectrum-viewer traces from the current input

        # Build UI
        self._build_ui()
        self._connect_signals()
        self._connect_engine()

    # ── Build ───────────────────────────────────────────────
    def _build_ui(self):
        central = GradientBackground()
        self._bg = central
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

    def set_glass(self, enabled: bool):
        """Tell the backdrop whether a system Mica/Acrylic material sits behind it."""
        self._bg.set_glass(enabled)

    # ── Connections ─────────────────────────────────────────
    def _connect_signals(self):
        # Sidebar navigation
        self._sidebar.navigation_changed.connect(self._navigate)

        # Theme toggle
        self._sidebar.theme_button.clicked.connect(self._toggle_theme)
        self._theme.theme_changed.connect(self._bg.set_theme)

        # Dashboard quick actions → navigate
        self._dashboard.action_requested.connect(self._navigate)

        # Input config → engine
        self._input_config.config_ready.connect(self._on_config_ready)
        self._input_config.input_file_loaded.connect(self._engine.load_input_file)

    def _connect_engine(self):
        """Wire AnalysisEngine signals to panels for live data flow."""
        e = self._engine

        # Engine logs → terminal
        e.log.connect(lambda msg: self._terminal.write(msg, "#8ea2c0"))
        e.error.connect(lambda step, msg: self._terminal.write_error(f"[{step}] {msg}"))
        e.error.connect(self._on_engine_error)

        # Mixture loaded → spectrum viewer + downstream panels
        e.mixture_loaded.connect(self._on_mixture_loaded)

        # Components loaded → calibration + peak editor
        e.components_loaded.connect(self._on_components_loaded)

        # Regions set → peak editor + fit runner
        e.regions_set.connect(self._on_regions_set)

        # Fit progress → fit runner convergence plot
        e.fit_progress.connect(self._fit_runner.update_progress)

        # Fit finished → results panel
        e.fit_finished.connect(self._on_fit_finished)

        # Region selector → engine
        self._regions.regions_confirmed.connect(self._on_regions_confirmed)

        # Fit runner start → engine
        self._fit_runner.fit_requested.connect(self._on_fit_requested)

        # Stop button → engine cancel; engine confirms via fit_cancelled (not an error)
        self._fit_runner.stop_requested.connect(self._engine.cancel_fit)
        e.fit_cancelled.connect(self._fit_runner.on_fit_cancelled)

        # Generated parameters → Peak Editor (peaks inside the fit windows)
        e.peaks_ready.connect(self._on_peaks_ready)
        self._peaks.peaks_modified.connect(self._on_peaks_saved)

        # Calibration done → apply drift/intensity to engine
        self._calibration.calibration_done.connect(self._on_calibration_done)

        # Results exports → terminal
        self._results.exported.connect(lambda msg: self._terminal.write_success(f"✅ {msg}"))

    # ── Engine event handlers ──────────────────────────────
    def _on_config_ready(self, config: dict):
        """When input config panel emits a complete config, start loading."""
        mix_path = config.get("mix_path", "")
        comp_paths = config.get("comp_paths", [])
        method = config.get("method", "tight")
        bds = config.get("bounds", {})
        proc = config.get("proc", {})

        if not mix_path:
            self._terminal.write_error("No mixture spectrum path specified")
            return

        # A new load starts a new analysis (drops previous params/regions/components)
        self._engine.reset()
        self._clear_analysis_views()

        # Set boundaries
        self._engine.set_boundaries(bds)

        # Convert proc options for pyihm
        proc_opt = {}
        wf_name = proc.get("wf", "none")
        if wf_name and wf_name != "none":
            proc_opt["wf"] = {"mode": wf_name}
        proc_opt["zf"] = proc.get("zf", False)
        proc_opt["blp"] = proc.get("blp", False)
        proc_opt["pknl"] = proc.get("pknl", False)
        proc_opt["adjph"] = proc.get("phase", False)

        # Store method for later
        self._state_method = method
        self._state_comp_paths = comp_paths

        # Load mixture (this chains to component loading via signal)
        self._engine.load_mixture(mix_path, proc_opt=proc_opt)

    def _on_mixture_loaded(self, ppm, data):
        """When mixture is loaded, push to viewer and auto-load components.

        FIX #3: Also checks engine state comp_paths (set by .inp file),
        not just _state_comp_paths from manual config.
        """
        # Fresh mixture → drop everything derived from a previous one
        self._clear_analysis_views()

        # Show spectrum in viewer panel
        self._spectrum.add_spectrum("Mixture", ppm, data)
        self._analysis_traces.append("Mixture")
        # Also set it in regions, calibration, peaks panels
        self._regions.set_spectrum(ppm, data)
        self._calibration.set_experimental(ppm, data)
        self._peaks.set_experimental(ppm, data)

        # Navigate to viewer
        self._navigate("viewer")

        # Auto-load components: check manual path first, then engine state (.inp)
        comp_paths = None
        if hasattr(self, "_state_comp_paths") and self._state_comp_paths:
            comp_paths = self._state_comp_paths
        elif self._engine._state["comp_paths"]:
            comp_paths = self._engine._state["comp_paths"]

        if comp_paths:
            self._engine.load_components(comp_paths)

    def _on_components_loaded(self, components, names):
        """When components are loaded, push to calibration and peak editor."""
        ppm = self._engine.ppm
        if ppm is None:
            return

        I = self._engine._state["I"] or 1.0

        # Replace, never stack: a repeated load must not duplicate components
        for tr in self._analysis_traces:
            if tr != "Mixture":
                self._spectrum.remove_spectrum(tr)
        self._analysis_traces = [t for t in self._analysis_traces if t == "Mixture"]
        self._calibration.clear_components()

        # Show components in spectrum viewer
        for i, (comp, name) in enumerate(zip(components, names)):
            self._spectrum.add_spectrum(name, ppm, comp * I)
            self._analysis_traces.append(name)

        # Push to calibration panel
        for i, (comp, name) in enumerate(zip(components, names)):
            self._calibration.add_component(name, ppm, comp * I)

        # Update dashboard stats
        if hasattr(self._dashboard, "_stat_cards") and len(self._dashboard._stat_cards) >= 2:
            self._dashboard._stat_cards[0].set_value("1")  # inputs loaded
            self._dashboard._stat_cards[1].set_value(str(len(components)))  # components

        self._terminal.write_success(f"✅ {len(components)} components loaded")

    def _clear_analysis_views(self):
        """Remove traces/components derived from the previously loaded input."""
        for tr in self._analysis_traces:
            self._spectrum.remove_spectrum(tr)
        self._analysis_traces = []
        self._calibration.clear_all()
        self._peaks.clear()

    def _on_peaks_ready(self, peaks: list):
        """Parameters were generated → fill the Peak Editor with the fitted peaks."""
        acqus = self._engine.acqus or {}
        sfo = acqus.get("SFO1")
        if sfo:
            self._peaks.set_spectrometer_frequency(float(sfo))
        self._peaks.set_peaks(peaks)
        self._terminal.write_success(f"✅ {len(peaks)} peaks loaded into the Peak Editor")

    def _on_peaks_saved(self, peaks: list):
        """Peak Editor 'Save' → write edited values into the fit's start parameters."""
        res = self._engine.apply_peak_edits(peaks)
        if res["applied"]:
            self._terminal.write_success(f"✅ Applied edits to {res['applied']} peak(s)")
        if res["added_ignored"]:
            self._terminal.write(
                f"⚠ {res['added_ignored']} added peak(s) not used by the fit "
                "(pyihm fits only the peaks of the component files)", "#fbbf24")
        if res["phase_ignored"]:
            self._terminal.write(
                f"⚠ Phase of {res['phase_ignored']} peak(s) is preview-only (not fitted)", "#fbbf24")

    def _on_regions_confirmed(self, regions: list):
        """When user confirms regions in the region selector panel."""
        self._engine.set_regions(regions)
        self._terminal.write_success(f"✅ {len(regions)} fit regions set")
        # Navigate to calibration
        self._navigate("calibration")

    def _on_calibration_done(self, cal_data):
        """Apply drift and intensity corrections from calibration panel to engine.

        FIX #1: After calibration, generate params (correct order:
        regions → calibrate → generate_params → fit).
        """
        for comp_idx, adjustments in cal_data.items():
            drift = adjustments.get("drift", 0.0)
            intensity = adjustments.get("intensity", 1.0)
            if abs(drift) > 1e-6:
                self._engine.apply_drift(comp_idx, drift)
            if abs(intensity - 1.0) > 1e-6:
                self._engine.set_initial_concentration(comp_idx, intensity)
        self._terminal.write_success("✅ Calibration applied")
        if self._calibration.write_cal_files:
            for path in self._engine.save_calibrated_components():
                self._terminal.write_success(f"✅ Saved {path}")

        # FIX #1: NOW generate params (after calibration, not after regions)
        if self._engine.has_mixture and self._engine.has_components and self._engine.has_regions:
            self._engine.generate_params()

        # Navigate to peak editor
        self._navigate("peaks")

    def _on_regions_set(self, regions: list):
        """After regions are set in engine.

        FIX #1: Does NOT auto-trigger generate_params anymore.
        Params are generated after calibration is done.
        Navigate to calibration so user can adjust drift/intensity.
        """
        pass  # intentionally empty — no auto-trigger

    def _on_fit_requested(self, method: str):
        """When user clicks Run Fit in the fit runner panel.

        FIX #6: Uses method from input config (via _state_method), not hardcoded.
        Also auto-generates params if user skipped calibration (optional step).
        """
        # Use the method from input config if fit_runner sends default
        actual_method = method or getattr(self, "_state_method", "tight")

        # If params not ready, try to generate them now
        if self._engine._state["param"] is None:
            if self._engine.has_mixture and self._engine.has_components and self._engine.has_regions:
                self._terminal.write("Auto-generating parameters...", "#8ea2c0")
                # generate_params is async, so connect a one-shot to run fit after
                def _after_params(param):
                    self._engine.params_ready.disconnect(_after_params)
                    self._engine.run_fit(actual_method)
                self._engine.params_ready.connect(_after_params)
                self._engine.generate_params()
                return
            else:
                self._terminal.write_error(
                    "Cannot start fit. Need: mixture + components + regions. "
                    "Complete previous steps."
                )
                self._fit_runner.abort_start()
                return

        self._engine.run_fit(actual_method, align=self._fit_runner.align_enabled)

    def _default_output_root(self) -> str | None:
        """Where to auto-save: the .inp's own output name, else next to the mixture."""
        root = self._engine.output_root
        if root:
            return root
        mix = self._engine._state["mix_path"]
        if not mix:
            return None
        stem = os.path.splitext(os.path.basename(os.path.normpath(mix)))[0] or "mixture"
        return os.path.join(os.path.dirname(os.path.abspath(mix)), f"{stem}-fit")

    def _autosave_results(self, results: dict):
        root = self._default_output_root()
        if root is None:
            self._terminal.write_error("Auto-save skipped: no output location known")
            return
        try:
            written = exporter.save_all(root, results, **self._engine.figure_options)
        except (exporter.ExportError, OSError, ValueError) as e:
            self._terminal.write_error(f"Auto-save failed: {e}")
            return
        self._terminal.write_success(f"✅ Outputs saved: {written.get('report', written['csv'])}")

    def _on_fit_finished(self, results: dict):
        """When fit completes, push results to results panel."""
        # Fit runner UI → complete (logs the elapsed time)
        self._fit_runner.on_fit_complete(results)

        self._results.set_results(
            ppm=results["ppm"],
            experimental=results["experimental"],
            total_fit=results["total_fit"],
            components=results["components"],
            concentrations=results["concentrations"],
            component_names=results.get("component_names"),
            export_data=results,
        )
        if self._fit_runner.autosave_enabled:
            self._autosave_results(results)
        # Update dashboard
        if hasattr(self._dashboard, "_stat_cards") and len(self._dashboard._stat_cards) >= 3:
            self._dashboard._stat_cards[2].set_value(f"{results['nfev']} evals")

        self._terminal.write_success("✅ Fit complete! Navigate to Results to see output.")
        self._navigate("results")

    def _on_engine_error(self, step: str, message: str):
        """Show a dialog when the engine reports an error."""
        # Stop fit runner if it was running
        if self._fit_runner._running:
            self._fit_runner.on_fit_error()
        # Show dialog
        QMessageBox.warning(self, f"Error — {step}",
                            f"An error occurred during '{step}':\n\n{message}")

    # Panel display names for status bar (#18)
    _PANEL_NAMES = {
        "home": "Dashboard",
        "input": "Input Configuration",
        "viewer": "Spectrum Viewer",
        "regions": "Region Selector",
        "calibration": "Calibration",
        "peaks": "Peak Editor",
        "fit": "Fit Runner",
        "results": "Results",
        "terminal": "Terminal",
    }

    def _navigate(self, name: str):
        """Switch to the panel identified by *name*."""
        if name in self._panels:
            self._stack.setCurrentWidget(self._panels[name])
            self._sidebar.set_active(name)
            display = self._PANEL_NAMES.get(name, name.replace('_', ' ').title())
            self._status_label.setText(f"  {display}")

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
            self._terminal.write("Available commands:", self._theme.get_color("accent"))
            self._terminal.write("  help          — show this help")
            self._terminal.write("  theme [dark|light] — switch theme")
            self._terminal.write("  goto <panel>  — navigate to a panel")
            self._terminal.write("  clear         — clear terminal")
            self._terminal.write("  version       — show version info")
        elif command == "clear":
            self._terminal.clear()
        elif command == "version":
            from app import __version__
            self._terminal.write(f"SpectraFlow v{__version__}", self._theme.get_color("accent"))
        elif command == "theme":
            if len(parts) > 1 and parts[1] in ("dark", "light"):
                app = QApplication.instance()
                self._theme.apply_theme(app, parts[1])
                is_dark = parts[1] == "dark"
                self._sidebar.set_theme_label(is_dark)
                self._theme_indicator.setText(f"{'🌙 Dark' if is_dark else '☀ Light'}")
                self._update_plot_themes()
                self._update_dwm_dark_mode(is_dark)  # Fix #15
                self._terminal.write_success(f"Theme set to {parts[1]}")
            else:
                self._terminal.write(f"Current: {self._theme.current_theme}")
        elif command == "goto":
            if len(parts) > 1:
                target = parts[1].lower()
                if target in self._panels:
                    self._navigate(target)
                    self._terminal.write_success(f"Navigated to {target}")
                else:
                    self._terminal.write_error(f"Unknown panel: {parts[1]}")
                    self._terminal.write(f"  Panels: {', '.join(self._panels.keys())}")
            else:
                self._terminal.write("Usage: goto <panel_name>")
                self._terminal.write(f"  Panels: {', '.join(self._panels.keys())}")
        else:
            self._terminal.write_error(f"Unknown command: {command}")
