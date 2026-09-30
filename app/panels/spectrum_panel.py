"""Spectrum viewer panel — load, explore, and overlay NMR spectra."""

import os
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QListWidget,
    QListWidgetItem, QSplitter, QMessageBox,
)
from PySide6.QtCore import Qt

from ..widgets.spectrum_viewer import SpectrumViewer


# Predefined trace colors
TRACE_COLORS = [
    "#4fc3f7", "#ff7043", "#66bb6a", "#ab47bc",
    "#ffa726", "#26c6da", "#ec407a", "#9ccc65",
    "#5c6bc0", "#8d6e63",
]


class SpectrumLoadError(ValueError):
    """Raised when a text spectrum cannot be interpreted as (ppm, intensity)."""


def load_text_spectrum(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Read a two-column (ppm, intensity) text/CSV spectrum.

    Whitespace-, comma-, semicolon- and tab-delimited files are accepted, as are
    ``#`` comments and a single non-numeric header row. A one-column file is
    rejected: it carries no chemical-shift axis and inventing one (point index)
    would silently plot data against a meaningless ppm scale.
    """
    arr = None
    last_err: Exception | None = None
    for delim in (None, ",", ";", "\t"):
        for skip in (0, 1):
            try:
                arr = np.loadtxt(path, delimiter=delim, comments="#", skiprows=skip, ndmin=2)
                break
            except ValueError as e:
                last_err = e
        if arr is not None:
            break
    if arr is None:
        raise SpectrumLoadError(f"Could not parse numeric data ({last_err}).")
    if arr.shape[1] < 2:
        raise SpectrumLoadError(
            "The file has a single column, so there is no chemical-shift axis. "
            "Expected two columns: ppm and intensity."
        )
    ppm, data = arr[:, 0], arr[:, 1]
    if ppm.size < 2:
        raise SpectrumLoadError("The file contains fewer than two data points.")
    if not (np.all(np.isfinite(ppm)) and np.all(np.isfinite(data))):
        raise SpectrumLoadError("The file contains NaN or infinite values.")
    return ppm, data


class SpectrumPanel(QWidget):
    """Full-page spectrum exploration with toolbar and spectra list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spectra: dict[str, dict] = {}  # name -> {ppm, data, visible, color}
        self._color_idx = 0
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # ── Toolbar ─────────────────────────────────────────
        tb = QHBoxLayout()
        tb.setSpacing(8)

        title = QLabel("Spectrum Viewer")
        title.setObjectName("subheading")
        tb.addWidget(title)
        tb.addStretch()

        load_btn = QPushButton("📂 Load File")
        load_btn.clicked.connect(self._load_file)
        tb.addWidget(load_btn)

        demo_btn = QPushButton("📊 Demo Data")
        demo_btn.clicked.connect(self._load_demo)
        tb.addWidget(demo_btn)

        auto_btn = QPushButton("⊞ Auto Scale")
        auto_btn.clicked.connect(lambda: self._viewer.auto_range())
        tb.addWidget(auto_btn)

        clear_btn = QPushButton("✗ Clear")
        clear_btn.clicked.connect(self._clear_all)
        tb.addWidget(clear_btn)

        root.addLayout(tb)

        # ── Main area (splitter: viewer | list) ─────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._viewer = SpectrumViewer()
        splitter.addWidget(self._viewer)

        # Side panel — loaded spectra list
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 0, 0, 0)
        sl.setSpacing(6)
        sl.addWidget(QLabel("Loaded Spectra", objectName="section_title"))

        self._spec_list = QListWidget()
        self._spec_list.setMaximumWidth(220)
        sl.addWidget(self._spec_list)

        rm_btn = QPushButton("Remove Selected")
        rm_btn.setObjectName("danger_btn")
        rm_btn.clicked.connect(self._remove_selected)
        sl.addWidget(rm_btn)

        splitter.addWidget(side)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, stretch=1)

    # ── Actions ─────────────────────────────────────────────
    def _next_color(self) -> str:
        c = TRACE_COLORS[self._color_idx % len(TRACE_COLORS)]
        self._color_idx += 1
        return c

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Spectrum", "",
            "Text/CSV (*.txt *.csv);;NMR Data (*.fid *.1r);;All (*)",
        )
        if not path:
            return
        try:
            ppm, data = load_text_spectrum(path)
        except (SpectrumLoadError, OSError) as e:
            QMessageBox.warning(self, "Could not load spectrum",
                                f"{os.path.basename(path)}\n\n{e}")
            return
        self.add_spectrum(os.path.basename(path), ppm, data)

    def _load_demo(self):
        """Generate a synthetic NMR-like spectrum for demo / testing."""
        N = 4096
        ppm = np.linspace(12, -1, N)
        # A few Lorentzian peaks at common chemical shifts
        data = np.zeros(N)
        peaks = [(7.26, 0.02, 1.0), (3.35, 0.03, 0.6),
                 (1.25, 0.04, 0.8), (4.80, 0.05, 0.3)]
        for center, width, amp in peaks:
            data += amp * width**2 / ((ppm - center)**2 + width**2)
        # Add a tiny bit of noise
        data += np.random.normal(0, 0.005, N)
        self.add_spectrum("Demo Spectrum", ppm, data)

    def add_spectrum(self, name: str, ppm: np.ndarray, data: np.ndarray):
        color = self._next_color()
        # Handle duplicate names — replace existing trace
        if name in self._spectra:
            self._viewer.remove_plot(name)
            # Remove old list item
            for i in range(self._spec_list.count()):
                if self._spec_list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                    self._spec_list.takeItem(i)
                    break
        self._spectra[name] = {"ppm": ppm, "data": data, "color": color}
        self._viewer.plot(ppm, data, name=name, color=color)
        item = QListWidgetItem(f"● {name}")
        item.setData(Qt.ItemDataRole.UserRole, name)
        self._spec_list.addItem(item)

    def _remove_selected(self):
        for item in self._spec_list.selectedItems():
            name = item.data(Qt.ItemDataRole.UserRole)
            if name and name in self._spectra:
                self._viewer.remove_plot(name)
                del self._spectra[name]
            self._spec_list.takeItem(self._spec_list.row(item))

    def _clear_all(self):
        self._viewer.clear()
        self._spectra.clear()
        self._spec_list.clear()
        self._color_idx = 0

    def update_theme(self, colors: dict):
        self._viewer.update_theme(colors)
