"""Results panel — concentrations table, fitted plot, export."""

import os

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from ..core import exporter
from ..widgets.spectrum_viewer import SpectrumViewer


class ResultsPanel(QWidget):
    """Display fit results: concentration table, fitted spectrum, export."""

    exported = Signal(str)   # human-readable description of what was written

    def __init__(self, parent=None):
        super().__init__(parent)
        self._export_data: dict | None = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # Header
        tb = QHBoxLayout()
        title = QLabel("Results")
        title.setObjectName("subheading")
        tb.addWidget(title)
        tb.addStretch()

        exp_csv = QPushButton("📄 Export CSV")
        exp_csv.clicked.connect(self._export_csv)
        tb.addWidget(exp_csv)

        exp_fig = QPushButton("🖼 Export Figures")
        exp_fig.clicked.connect(self._export_figures)
        tb.addWidget(exp_fig)

        exp_report = QPushButton("📋 Export Report")
        exp_report.setObjectName("primary_btn")
        exp_report.clicked.connect(self._export_report)
        tb.addWidget(exp_report)

        root.addLayout(tb)

        # ── Top: concentration table ────────────────────────
        table_card = QFrame()
        table_card.setObjectName("card")
        tc_lay = QVBoxLayout(table_card)
        tc_lay.setContentsMargins(12, 8, 12, 8)
        tc_lay.setSpacing(4)
        tc_lay.addWidget(QLabel("Component Concentrations", objectName="section_title"))

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Component", "Concentration (%)", "Relative", "H correction"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setAlternatingRowColors(True)
        self._table.setMaximumHeight(200)
        tc_lay.addWidget(self._table)

        root.addWidget(table_card)

        # ── Middle: fitted spectrum plot ────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        plot_card = QFrame()
        plot_card.setObjectName("card")
        pc_lay = QVBoxLayout(plot_card)
        pc_lay.setContentsMargins(8, 8, 8, 8)
        pc_lay.addWidget(QLabel("Fitted Spectrum", objectName="section_title"))
        self._viewer = SpectrumViewer()
        pc_lay.addWidget(self._viewer)
        splitter.addWidget(plot_card)

        # Residual histogram
        hist_card = QFrame()
        hist_card.setObjectName("card")
        hc_lay = QVBoxLayout(hist_card)
        hc_lay.setContentsMargins(8, 8, 8, 8)
        hc_lay.addWidget(QLabel("Residual Distribution", objectName="section_title"))
        self._hist_viewer = SpectrumViewer(show_coords=False)
        self._hist_viewer.set_xlabel("Residual")
        self._hist_viewer.set_ylabel("Count")
        self._hist_viewer.plot_widget.invertX(False)
        hc_lay.addWidget(self._hist_viewer)
        splitter.addWidget(hist_card)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

        # Placeholder message
        self._placeholder = QLabel("Run a fit first to see results here.")
        self._placeholder.setObjectName("muted")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._placeholder)

    # ── Data loading ────────────────────────────────────────
    def set_results(
        self,
        ppm: np.ndarray,
        experimental: np.ndarray,
        total_fit: np.ndarray,
        components: list[np.ndarray],
        concentrations: list[float],
        component_names: list[str] | None = None,
        export_data: dict | None = None,
    ):
        """Populate the results view with fit output.

        ``export_data`` is the engine's full results dict; it enables the
        report / figure exports and fills the H-correction column.
        """
        n = len(concentrations)
        if n == 0:
            self._export_data = None
            self._table.setRowCount(0)
            self._placeholder.setVisible(True)
            return
        self._placeholder.setVisible(False)
        self._export_data = export_data or {
            "ppm": ppm, "experimental": experimental, "total_fit": total_fit,
            "components": components, "concentrations": concentrations,
            "component_names": component_names,
        }
        hs = self._export_data.get("Hs")

        self._table.setRowCount(n)
        positives = [c for c in concentrations if c > 0]
        c_min = min(positives) if positives else None  # zero must not rescale the ratios
        for i, c in enumerate(concentrations):
            name = component_names[i] if component_names else f"Component {i+1}"
            self._table.setItem(i, 0, QTableWidgetItem(name))
            self._table.setItem(i, 1, QTableWidgetItem(f"{c*100:.4f}"))
            self._table.setItem(i, 2, QTableWidgetItem(f"{c/c_min:.4f}" if c_min else "—"))
            h_text = f"{hs[i]:.3f}" if hs is not None and i < len(hs) else "—"
            self._table.setItem(i, 3, QTableWidgetItem(h_text))

        # Spectrum plot
        self._viewer.clear()
        self._viewer.plot(ppm, experimental, name="Experimental", color="#e4e8ee", width=1.2)
        self._viewer.plot(ppm, total_fit, name="Fit", color="#4fc3f7", width=1.5)

        colors = ["#ff7043", "#66bb6a", "#ab47bc", "#ffa726", "#26c6da",
                  "#ec407a", "#9ccc65", "#5c6bc0", "#8d6e63", "#78909c"]
        for i, comp in enumerate(components):
            c = colors[i % len(colors)]
            self._viewer.plot(ppm, comp, name=f"Comp {i+1}", color=c, width=0.8)

        # Residuals
        residuals = experimental - total_fit
        floor = min(float(np.min(experimental)), float(np.min(total_fit)))
        offset = floor - 1.2 * float(np.max(np.abs(residuals)))  # sit below the baseline, no overlap
        self._viewer.plot(ppm, residuals + offset,
                         name="Residuals", color="#66bb6a", width=0.7)

        # Histogram
        self._hist_viewer.clear()
        counts, bin_edges = np.histogram(residuals, bins=80)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        self._hist_viewer.plot(bin_centers, counts.astype(float),
                              name="Histogram", color="#66bb6a", width=2)

    # ── Export ──────────────────────────────────────────────
    def _has_results(self) -> bool:
        if self._export_data is None:
            QMessageBox.information(self, "Export", "Run a fit first to have something to export.")
            return False
        return True

    def _run_export(self, title: str, action):
        try:
            message = action()
        except (exporter.ExportError, OSError, ValueError) as e:
            QMessageBox.warning(self, title, str(e))
            return
        self.exported.emit(message)

    def _export_csv(self):
        if not self._has_results():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "results.csv", "CSV (*.csv)")
        if not path:
            return

        def action():
            exporter.write_csv(path, self._export_data)
            stem, ext = os.path.splitext(path)
            conc = exporter.write_concentrations_csv(f"{stem}-concentrations{ext or '.csv'}", self._export_data)
            return f"Exported {path} and {conc}"

        self._run_export("Export CSV", action)

    def _export_figures(self):
        if not self._has_results():
            return
        folder = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if not folder:
            return

        def action():
            files = exporter.save_figures(folder, "fit", self._export_data)
            return f"Exported {len(files)} figure(s) to {folder}"

        self._run_export("Export Figures", action)

    def _export_report(self):
        if not self._has_results():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Report", "fit_report.out", "pyihm report (*.out);;Text (*.txt)")
        if not path:
            return
        self._run_export("Export Report", lambda: f"Exported {exporter.write_report(path, self._export_data)}")

    def update_theme(self, colors: dict):
        self._viewer.update_theme(colors)
        self._hist_viewer.update_theme(colors)
