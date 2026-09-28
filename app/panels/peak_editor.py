"""Peak editor panel — adjust individual peak parameters interactively."""

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QComboBox, QSplitter,
    QSpinBox,
)
from PySide6.QtCore import Signal, Qt

from ..widgets.spectrum_viewer import SpectrumViewer
from ..widgets.parameter_slider import ParameterSlider


class PeakEditorPanel(QWidget):
    """Edit individual peak parameters (position, width, intensity, shape, phase)."""

    peaks_modified = Signal(list)  # list of peak-parameter dicts

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks: list[dict] = []
        self._active = 0
        self._exp_ppm = None
        self._exp_data = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # Header
        tb = QHBoxLayout()
        title = QLabel("Peak Editor")
        title.setObjectName("subheading")
        tb.addWidget(title)
        tb.addStretch()

        add_btn = QPushButton("+ Add Peak")
        add_btn.setObjectName("primary_btn")
        add_btn.clicked.connect(self._add_peak)
        tb.addWidget(add_btn)

        rm_btn = QPushButton("− Remove Peak")
        rm_btn.setObjectName("danger_btn")
        rm_btn.clicked.connect(self._remove_peak)
        tb.addWidget(rm_btn)

        save_btn = QPushButton("💾 Save")
        save_btn.clicked.connect(self._save)
        tb.addWidget(save_btn)

        root.addLayout(tb)

        # Splitter: viewer | param controls
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._viewer = SpectrumViewer()
        splitter.addWidget(self._viewer)

        # Right panel
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        rl.setSpacing(10)

        # Peak selector
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Active Peak:"))
        self._peak_spin = QSpinBox()
        self._peak_spin.setMinimum(1)
        self._peak_spin.setMaximum(1)
        self._peak_spin.valueChanged.connect(self._on_peak_selected)
        sel_row.addWidget(self._peak_spin)
        self._peak_count = QLabel("/ 0")
        self._peak_count.setObjectName("muted")
        sel_row.addWidget(self._peak_count)
        sel_row.addStretch()
        rl.addLayout(sel_row)

        # Parameter sliders in a card
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(6)

        cl.addWidget(QLabel("Peak Parameters", objectName="section_title"))

        self._sl_pos = ParameterSlider("δ position", -2.0, 14.0, 5.0, 0.001, "ppm", 4)
        self._sl_fwhm = ParameterSlider("Γ linewidth", 0.0, 100.0, 5.0, 0.1, "Hz", 2)
        self._sl_k = ParameterSlider("k intensity", 0.0, 2.0, 0.5, 0.001, "", 4)
        self._sl_beta = ParameterSlider("β Gauss frac", 0.0, 1.0, 0.5, 0.01, "", 3)
        self._sl_phi = ParameterSlider("φ phase", -180.0, 180.0, 0.0, 0.5, "°", 1)

        for s in (self._sl_pos, self._sl_fwhm, self._sl_k, self._sl_beta, self._sl_phi):
            s.value_changed.connect(self._on_param_changed)
            cl.addWidget(s)

        rl.addWidget(card)

        # Group selector
        grp_row = QHBoxLayout()
        grp_row.addWidget(QLabel("Group:"))
        self._grp_spin = QSpinBox()
        self._grp_spin.setMinimum(0)
        self._grp_spin.setMaximum(99)
        self._grp_spin.valueChanged.connect(self._on_param_changed)
        grp_row.addWidget(self._grp_spin)
        grp_row.addStretch()
        rl.addLayout(grp_row)

        rl.addStretch()
        right.setMinimumWidth(280)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)

        root.addWidget(splitter, stretch=1)

    # ── Data ────────────────────────────────────────────────
    def set_experimental(self, ppm: np.ndarray, data: np.ndarray):
        self._exp_ppm = ppm
        self._exp_data = data
        self._viewer.plot(ppm, data, name="Experimental", color="#e4e8ee", width=1.2)

    def set_peaks(self, peaks: list[dict]):
        """peaks: list of {u, fwhm, k, b, phi, group}"""
        self._peaks = [dict(p) for p in peaks]
        self._peak_spin.setMaximum(max(1, len(self._peaks)))
        self._peak_count.setText(f"/ {len(self._peaks)}")
        if self._peaks:
            self._peak_spin.setValue(1)
            self._load_peak(0)
        self._redraw_all()

    # ── Peak management ─────────────────────────────────────
    def _add_peak(self):
        center = 5.0
        if self._exp_ppm is not None:
            center = float(np.mean(self._viewer.plot_widget.viewRange()[0]))
        self._peaks.append({
            "u": center, "fwhm": 5.0, "k": 0.5, "b": 0.5, "phi": 0.0, "group": 0
        })
        self._peak_spin.setMaximum(len(self._peaks))
        self._peak_count.setText(f"/ {len(self._peaks)}")
        self._peak_spin.setValue(len(self._peaks))
        self._redraw_all()

    def _remove_peak(self):
        if not self._peaks:
            return
        idx = self._peak_spin.value() - 1
        self._peaks.pop(idx)
        self._peak_spin.setMaximum(max(1, len(self._peaks)))
        self._peak_count.setText(f"/ {len(self._peaks)}")
        if self._peaks:
            self._load_peak(min(idx, len(self._peaks) - 1))
        self._redraw_all()

    def _on_peak_selected(self, val):
        idx = val - 1
        if 0 <= idx < len(self._peaks):
            self._active = idx
            self._load_peak(idx)

    def _load_peak(self, idx):
        """Populate sliders from peak dict."""
        if idx >= len(self._peaks):
            return
        p = self._peaks[idx]
        for sl, key in [(self._sl_pos, "u"), (self._sl_fwhm, "fwhm"),
                        (self._sl_k, "k"), (self._sl_beta, "b"),
                        (self._sl_phi, "phi")]:
            sl.blockSignals(True)
            sl.value = p[key]
            sl.blockSignals(False)
        self._grp_spin.blockSignals(True)
        self._grp_spin.setValue(int(p.get("group", 0)))
        self._grp_spin.blockSignals(False)

    def _on_param_changed(self, _=None):
        if not self._peaks:
            return
        idx = self._active
        self._peaks[idx]["u"] = self._sl_pos.value
        self._peaks[idx]["fwhm"] = self._sl_fwhm.value
        self._peaks[idx]["k"] = self._sl_k.value
        self._peaks[idx]["b"] = self._sl_beta.value
        self._peaks[idx]["phi"] = self._sl_phi.value
        self._peaks[idx]["group"] = self._grp_spin.value()
        self._redraw_all()

    # ── Drawing ─────────────────────────────────────────────
    def _redraw_all(self):
        """Redraw all peaks as simple Lorentzian approximations for visual feedback."""
        if self._exp_ppm is None:
            return
        ppm = self._exp_ppm
        total = np.zeros_like(ppm, dtype=float)
        colors = ["#ff7043", "#66bb6a", "#ab47bc", "#ffa726", "#26c6da",
                  "#ec407a", "#9ccc65", "#5c6bc0", "#8d6e63", "#78909c"]
        for i, p in enumerate(self._peaks):
            # Simple Lorentzian for preview
            gamma = p["fwhm"] / 100.0  # rough ppm conversion
            peak_data = p["k"] * gamma**2 / ((ppm - p["u"])**2 + gamma**2)
            total += peak_data
            c = colors[i % len(colors)]
            width = 2.0 if i == self._active else 0.8
            self._viewer.plot(ppm, peak_data, name=f"Peak_{i+1}", color=c, width=width)
        self._viewer.plot(ppm, total, name="Total Fit", color="#4fc3f7", width=1.5)

    def _save(self):
        self.peaks_modified.emit(self._peaks)

    def update_theme(self, colors: dict):
        self._viewer.update_theme(colors)
