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

    FG_TRACES = frozenset({"Experimental", "Mixture"})

    region_added = Signal(float, float)
    point_clicked = Signal(float, float)

    def __init__(self, parent=None, show_coords: bool = True):
        super().__init__(parent)
        self._plots: dict[str, pg.PlotDataItem] = {}
        self._pens: dict[str, tuple[str, float]] = {}  # name -> (color, width) last applied
        self._regions: list[pg.LinearRegionItem] = []
        self._show_coords = show_coords
        self._fg = "#e4e8ee"
        self._build_ui()

    # ── Build ───────────────────────────────────────────────
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._pw = pg.PlotWidget()
        self._pw.setBackground("#141824")
        self._pw.showGrid(x=True, y=True, alpha=0.15)
        # Units go in the label text, not in pyqtgraph's `units=`: with units set,
        # pyqtgraph auto-applies SI prefixes ("Ma.u." for 3e8, "mppm" when zoomed),
        # which is wrong for arbitrary units. Ticks fall back to plain/scientific.
        self._pw.setLabel("bottom", "δ (ppm)")
        self._pw.setLabel("left", "Intensity (a.u.)")
        for axis_name in ("bottom", "left"):
            self._pw.getAxis(axis_name).enableAutoSIPrefix(False)
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
        """Add or update a named trace (data, colour and width)."""
        if name in self.FG_TRACES:
            color = self._fg
        if name in self._plots:
            item = self._plots[name]
            item.setData(ppm, data)
            if self._pens.get(name) != (color, width):
                item.setPen(pg.mkPen(color=color, width=width))
        else:
            item = self._pw.plot(ppm, data, pen=pg.mkPen(color=color, width=width), name=name)
            self._plots[name] = item
        self._pens[name] = (color, width)
        return item

    def remove_plot(self, name: str):
        """Remove a named trace."""
        if name in self._plots:
            self._pw.removeItem(self._plots.pop(name))
            self._pens.pop(name, None)

    def clear(self):
        """Remove all traces and regions, keep crosshair."""
        for item in self._plots.values():
            self._pw.removeItem(item)
        self._plots.clear()
        self._pens.clear()
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
        self._fg = fg
        for axis_name in ("bottom", "left"):
            ax = self._pw.getAxis(axis_name)
            ax.setPen(pg.mkPen(fg))
            ax.setTextPen(pg.mkPen(fg))
        accent = colors.get("accent", "#60a5fa")
        pen_ch = pg.mkPen(accent, width=1, style=Qt.PenStyle.DashLine)
        self._vline.setPen(pen_ch)
        self._hline.setPen(pen_ch)
        for name in self.FG_TRACES:
            item = self._plots.get(name)
            if item is not None:
                width = self._pens.get(name, (fg, 1.2))[1]
                item.setPen(pg.mkPen(fg, width=width))
                self._pens[name] = (fg, width)
