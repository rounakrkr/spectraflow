"""Spectrum viewer panel — load, explore, and overlay NMR spectra."""

import os
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QFileDialog, QListWidget,
    QListWidgetItem, QCheckBox, QSplitter,
)
from PySide6.QtCore import Qt, Signal

from ..widgets.spectrum_viewer import SpectrumViewer


# Predefined trace colors
TRACE_COLORS = [
    "#4fc3f7", "#ff7043", "#66bb6a", "#ab47bc",
    "#ffa726", "#26c6da", "#ec407a", "#9ccc65",
    "#5c6bc0", "#8d6e63",
]


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
            arr = np.loadtxt(path)
            if arr.ndim == 1:
                ppm = np.arange(len(arr))[::-1]
                data = arr
            else:
                ppm = arr[:, 0]
                data = arr[:, 1]
            name = os.path.basename(path)
            self.add_spectrum(name, ppm, data)
        except Exception as e:
            import sys
            print(f"[SpectraFlow] Error loading {path}: {e}", file=sys.stderr)

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
