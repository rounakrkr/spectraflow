"""
Interactive spectrum viewer built on PyQtGraph.
Provides NMR-convention plotting (inverted X axis), crosshair,
coordinate readout, region selection, and theme-aware colors.
"""

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont


class SpectrumViewer(QWidget):
    """Fast, interactive NMR spectrum plot widget."""

    region_added = Signal(float, float)
    point_clicked = Signal(float, float)

    def __init__(self, parent=None, show_coords: bool = True):
        super().__init__(parent)
        self._plots: dict[str, pg.PlotDataItem] = {}
        self._regions: list[pg.LinearRegionItem] = []
        self._show_coords = show_coords
        self._build_ui()

    # ── Build ───────────────────────────────────────────────
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._pw = pg.PlotWidget()
        self._pw.setBackground("#141824")
        self._pw.showGrid(x=True, y=True, alpha=0.15)
        self._pw.setLabel("bottom", "δ", units="ppm")
        self._pw.setLabel("left", "Intensity", units="a.u.")
        self._pw.invertX(True)  # NMR convention

        # Style axes
        for axis_name in ("bottom", "left"):
            ax = self._pw.getAxis(axis_name)
            ax.setPen(pg.mkPen("#8892a0"))
            ax.setTextPen(pg.mkPen("#8892a0"))
            ax.setStyle(tickFont=QFont("Segoe UI", 9))

        # Crosshair
        pen_ch = pg.mkPen("#4fc3f7", width=1, style=Qt.PenStyle.DashLine)
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=pen_ch)
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=pen_ch)
        self._pw.addItem(self._vline, ignoreBounds=True)
        self._pw.addItem(self._hline, ignoreBounds=True)
        self._vline.setVisible(False)
        self._hline.setVisible(False)

        self._pw.scene().sigMouseMoved.connect(self._on_mouse_moved)
        lay.addWidget(self._pw)

        # Coordinate readout
        if self._show_coords:
            self._coord = QLabel("δ: — ppm  |  I: —")
            self._coord.setObjectName("muted")
            self._coord.setContentsMargins(8, 2, 8, 4)
            lay.addWidget(self._coord)

    # ── Mouse ───────────────────────────────────────────────
    def _on_mouse_moved(self, pos):
        if self._pw.sceneBoundingRect().contains(pos):
            pt = self._pw.plotItem.vb.mapSceneToView(pos)
            self._vline.setPos(pt.x())
            self._hline.setPos(pt.y())
            self._vline.setVisible(True)
            self._hline.setVisible(True)
            if self._show_coords:
                self._coord.setText(f"δ: {pt.x():.4f} ppm  |  I: {pt.y():.3e}")

    # ── Public API ──────────────────────────────────────────
    def plot(self, ppm: np.ndarray, data: np.ndarray,
             name: str = "spectrum", color: str = "#4fc3f7",
             width: float = 1.5) -> pg.PlotDataItem:
        """Add or update a named trace."""
        if name in self._plots:
            self._plots[name].setData(ppm, data)
        else:
            pen = pg.mkPen(color=color, width=width)
            item = self._pw.plot(ppm, data, pen=pen, name=name)
            self._plots[name] = item
        return self._plots[name]

    def remove_plot(self, name: str):
        """Remove a named trace."""
        if name in self._plots:
            self._pw.removeItem(self._plots.pop(name))

    def clear(self):
        """Remove all traces and regions, keep crosshair."""
        for item in self._plots.values():
            self._pw.removeItem(item)
        self._plots.clear()
        for r in self._regions:
            self._pw.removeItem(r)
        self._regions.clear()

    def add_region(self, left: float, right: float,
                   color: str = "#4fc3f733",
                   movable: bool = True) -> pg.LinearRegionItem:
        """Add a highlighted region band."""
        region = pg.LinearRegionItem(
            [left, right], brush=pg.mkBrush(color), movable=movable
        )
        self._pw.addItem(region)
        self._regions.append(region)
        return region

    def remove_region(self, region: pg.LinearRegionItem):
        if region in self._regions:
            self._pw.removeItem(region)
            self._regions.remove(region)

    def get_regions(self) -> list[tuple[float, float]]:
        return [tuple(r.getRegion()) for r in self._regions]

    def set_xlabel(self, label: str):
        self._pw.setLabel("bottom", label)

    def set_ylabel(self, label: str):
        self._pw.setLabel("left", label)

    def auto_range(self):
        self._pw.autoRange()

    @property
    def plot_widget(self) -> pg.PlotWidget:
        """Direct access when you need pyqtgraph-level control."""
        return self._pw

    # ── Theming ─────────────────────────────────────────────
    def update_theme(self, colors: dict):
        """Repaint plot background/axes/crosshair for current theme."""
        self._pw.setBackground(colors.get("plot_bg", "#141824"))
        fg = colors.get("plot_fg", "#e4e8ee")
        for axis_name in ("bottom", "left"):
            ax = self._pw.getAxis(axis_name)
            ax.setPen(pg.mkPen(fg))
            ax.setTextPen(pg.mkPen(fg))
        accent = colors.get("accent", "#4fc3f7")
        pen_ch = pg.mkPen(accent, width=1, style=Qt.PenStyle.DashLine)
        self._vline.setPen(pen_ch)
        self._hline.setPen(pen_ch)
