"""Region selector panel — draw and manage fit regions on the spectrum."""

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Signal, Qt

from ..widgets.spectrum_viewer import SpectrumViewer


class RegionSelectorPanel(QWidget):
    """Select spectral windows for fitting by drawing regions on the plot."""

    regions_changed = Signal(list)  # list of (left, right) tuples

    def __init__(self, parent=None):
        super().__init__(parent)
        self._regions: list = []  # list of LinearRegionItems
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # Header
        tb = QHBoxLayout()
        title = QLabel("Region Selector")
        title.setObjectName("subheading")
        tb.addWidget(title)
        tb.addStretch()

        self._add_btn = QPushButton("+ Add Region")
        self._add_btn.setObjectName("primary_btn")
        self._add_btn.clicked.connect(self._add_region)
        tb.addWidget(self._add_btn)

        rm_btn = QPushButton("Remove Selected")
        rm_btn.setObjectName("danger_btn")
        rm_btn.clicked.connect(self._remove_selected)
        tb.addWidget(rm_btn)

        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._clear_all)
        tb.addWidget(clear_btn)

        root.addLayout(tb)

        hint = QLabel("Click 'Add Region' then drag the blue band on the plot to define each fitting window.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # Viewer
        self._viewer = SpectrumViewer()
        root.addWidget(self._viewer, stretch=1)

        # Region list
        bot = QHBoxLayout()
        bot.setSpacing(12)

        list_frame = QFrame()
        list_frame.setObjectName("card")
        lf_lay = QVBoxLayout(list_frame)
        lf_lay.setContentsMargins(12, 8, 12, 8)
        lf_lay.setSpacing(4)
        lf_lay.addWidget(QLabel("Selected Regions (ppm)", objectName="section_title"))

        self._region_list = QListWidget()
        self._region_list.setMaximumHeight(120)
        lf_lay.addWidget(self._region_list)

        bot.addWidget(list_frame, stretch=1)
        root.addLayout(bot)

    # ── Actions ─────────────────────────────────────────────
    def _add_region(self):
        """Add a new draggable region to the plot."""
        # Default span: center ±0.5 ppm (user drags to adjust)
        xlims = self._viewer.plot_widget.viewRange()[0]
        center = (xlims[0] + xlims[1]) / 2
        half = (xlims[1] - xlims[0]) * 0.15
        region = self._viewer.add_region(center - half, center + half, "#4fc3f740")
        region.sigRegionChangeFinished.connect(self._update_list)
        self._regions.append(region)
        self._update_list()

    def _remove_selected(self):
        idx = self._region_list.currentRow()
        if 0 <= idx < len(self._regions):
            self._viewer.remove_region(self._regions.pop(idx))
            self._update_list()

    def _clear_all(self):
        for r in self._regions:
            self._viewer.remove_region(r)
        self._regions.clear()
        self._update_list()

    def _update_list(self, _=None):
        self._region_list.clear()
        result = []
        for i, r in enumerate(self._regions):
            lo, hi = r.getRegion()
            lo, hi = min(lo, hi), max(lo, hi)
            result.append((hi, lo))  # NMR convention: high ppm first
            self._region_list.addItem(f"Region {i+1}:  {hi:.3f} → {lo:.3f} ppm")
        self.regions_changed.emit(result)

    def get_regions(self) -> list[tuple[float, float]]:
        return [(max(r.getRegion()), min(r.getRegion())) for r in self._regions]

    def set_spectrum(self, ppm: np.ndarray, data: np.ndarray, name: str = "Mixture"):
        self._viewer.plot(ppm, data, name=name, color="#e4e8ee", width=1.2)

    def update_theme(self, colors: dict):
        self._viewer.update_theme(colors)
