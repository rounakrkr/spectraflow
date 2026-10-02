"""Peak editor panel — adjust individual peak parameters interactively."""

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSplitter,
    QSpinBox,
)
from PySide6.QtCore import Signal, Qt

from ..theme.theme_manager import COLORS
from ..widgets.spectrum_viewer import SpectrumViewer
from ..widgets.parameter_slider import ParameterSlider


_LN2_4 = 4.0 * np.log(2.0)


def pseudo_voigt(ppm: np.ndarray, u: float, fwhm_hz: float, sfo_mhz: float,
                 beta: float, phi_deg: float = 0.0) -> np.ndarray:
    """Preview line shape for one peak (pseudo-Voigt, area-agnostic).

    ``fwhm_hz`` is the full width at half maximum in Hz, converted to ppm with
    the spectrometer frequency ``sfo_mhz`` (Hz / MHz = ppm). ``beta`` is the
    Gaussian fraction (0 = pure Lorentzian). Phase mixes in the dispersive
    component, taken with the Lorentzian dispersion shape for both fractions.
    This is a visual guide, not a reimplementation of the fitting model.
    """
    w = max(fwhm_hz / max(sfo_mhz, 1e-9), 1e-9)          # FWHM in ppm
    x = (np.asarray(ppm, dtype=float) - u) / w
    lorentz = 1.0 / (1.0 + 4.0 * x**2)
    gauss = np.exp(-_LN2_4 * x**2)
    absorptive = (1.0 - beta) * lorentz + beta * gauss
    if phi_deg == 0.0:
        return absorptive
    dispersive = 2.0 * x * lorentz
    phi = np.deg2rad(phi_deg)
    return np.cos(phi) * absorptive + np.sin(phi) * dispersive


class PeakEditorPanel(QWidget):
    """Edit individual peak parameters (position, width, intensity, shape, phase)."""

    peaks_modified = Signal(list)  # list of peak-parameter dicts

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks: list[dict] = []
        self._active = 0
        self._drawn_peak_count = 0
        self._preview_scale = 1.0      # raw line shapes → experimental intensity units
        self._exp_ppm = None
        self._exp_data = None
        self._colors = COLORS["dark"]
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

        self._peak_info = QLabel("No peaks yet — run Calibration to generate parameters.")
        self._peak_info.setObjectName("muted")
        self._peak_info.setWordWrap(True)
        rl.addWidget(self._peak_info)

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

        # Spectrometer frequency: needed to turn Hz linewidths into ppm for the preview
        sfo_card = QFrame()
        sfo_card.setObjectName("card")
        sl_ = QVBoxLayout(sfo_card)
        sl_.setContentsMargins(12, 12, 12, 12)
        sl_.addWidget(QLabel("Spectrometer", objectName="section_title"))
        self._sl_sfo = ParameterSlider("SFO1", 50.0, 1200.0, 400.0, 0.1, "MHz", 1)
        self._sl_sfo.value_changed.connect(lambda _v: self._redraw_all())
        sl_.addWidget(self._sl_sfo)
        rl.addWidget(sfo_card)

        # One shared column grid for every slider so labels never clip and tracks align
        self._sliders = [self._sl_pos, self._sl_fwhm, self._sl_k, self._sl_beta,
                         self._sl_phi, self._sl_sfo]
        ParameterSlider.align_group(self._sliders)

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
        right.setMinimumWidth(400)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)
        splitter.setCollapsible(1, False)
        splitter.setSizes([900, 420])

        root.addWidget(splitter, stretch=1)

    # ── Data ────────────────────────────────────────────────
    def showEvent(self, event):
        super().showEvent(event)
        ParameterSlider.align_group(self._sliders)   # sizes depend on the active theme

    def set_spectrometer_frequency(self, sfo_mhz: float):
        """Set the 1H Larmor frequency (MHz) used by the Hz→ppm preview conversion."""
        sfo = float(sfo_mhz)
        lo, hi = self._sl_sfo.spinbox.minimum(), self._sl_sfo.spinbox.maximum()
        if not lo <= sfo <= hi:
            self._sl_sfo.set_range(min(lo, sfo * 0.5), max(hi, sfo * 1.5))
        self._sl_sfo.value = sfo

    def clear(self):
        """Forget all peaks and traces (new input loaded)."""
        for i in range(self._drawn_peak_count):
            self._viewer.remove_plot(f"Peak_{i+1}")
        self._viewer.remove_plot("Total Fit")
        self._drawn_peak_count = 0
        self._peaks = []
        self._active = 0
        self._peak_spin.blockSignals(True)
        self._peak_spin.setMaximum(1)
        self._peak_spin.setValue(1)
        self._peak_spin.blockSignals(False)
        self._peak_count.setText("/ 0")
        self._peak_info.setText("No peaks yet — run Calibration to generate parameters.")

    def _fit_slider_ranges(self):
        """Widen slider ranges so every loaded peak value is reachable."""
        if not self._peaks:
            return
        us = [p["u"] for p in self._peaks]
        lo, hi = min(us), max(us)
        if self._exp_ppm is not None and len(self._exp_ppm):
            lo, hi = min(lo, float(np.min(self._exp_ppm))), max(hi, float(np.max(self._exp_ppm)))
        self._sl_pos.set_range(min(-2.0, lo - 0.5), max(14.0, hi + 0.5))
        self._sl_fwhm.set_range(0.0, max(100.0, 1.5 * max(p["fwhm"] for p in self._peaks)))
        self._sl_k.set_range(0.0, max(2.0, 1.25 * max(p["k"] for p in self._peaks)))

    def set_experimental(self, ppm: np.ndarray, data: np.ndarray):
        self._exp_ppm = ppm
        self._exp_data = data
        self._viewer.plot(ppm, data, name="Experimental", color="#e4e8ee", width=1.2)

    def set_peaks(self, peaks: list[dict]):
        """peaks: list of {u, fwhm, k, b, phi, group[, label, key]}

        ``label`` (e.g. "bzac · peak 3") is shown under the selector; ``key``
        is the engine's parameter prefix, passed back untouched on save.
        """
        self._peaks = [dict(p) for p in peaks]
        self._active = 0
        self._fit_slider_ranges()
        self._peak_spin.blockSignals(True)
        self._peak_spin.setMaximum(max(1, len(self._peaks)))
        self._peak_spin.setValue(1)
        self._peak_spin.blockSignals(False)
        self._peak_count.setText(f"/ {len(self._peaks)}")
        self._calibrate_preview_scale()
        if self._peaks:
            self._load_peak(0)
        else:
            self._peak_info.setText("No peaks in the selected fit regions.")
        self._redraw_all()

    def _calibrate_preview_scale(self):
        """Fix the preview's vertical scale once, when peaks are loaded.

        Raw k·shape is ~1 while the spectrum is ~1e8, so the traces would be
        invisible. The scale is frozen (not re-fitted on every slider move) so
        that changing k still visibly changes the height.
        """
        self._preview_scale = 1.0
        if self._exp_ppm is None or self._exp_data is None or not self._peaks:
            return
        ppm = np.asarray(self._exp_ppm, dtype=float)
        total = np.zeros_like(ppm)
        for p in self._peaks:
            total += p["k"] * pseudo_voigt(ppm, p["u"], p["fwhm"], self._sl_sfo.value, p["b"], 0.0)
        us = [p["u"] for p in self._peaks]
        win = (ppm >= min(us) - 0.2) & (ppm <= max(us) + 0.2)
        exp_peak = float(np.max(np.abs(np.asarray(self._exp_data)[win]))) if win.any() else 0.0
        tot_peak = float(np.max(np.abs(total)))
        if exp_peak > 0 and tot_peak > 0:
            self._preview_scale = exp_peak / tot_peak

    # ── Peak management ─────────────────────────────────────
    def _add_peak(self):
        center = 5.0
        if self._exp_ppm is not None:
            center = float(np.mean(self._viewer.plot_widget.viewRange()[0]))
        self._peaks.append({
            "u": center, "fwhm": 5.0, "k": 0.5, "b": 0.5, "phi": 0.0, "group": 0
        })
        new_idx = len(self._peaks) - 1
        self._peak_spin.setMaximum(len(self._peaks))
        self._peak_count.setText(f"/ {len(self._peaks)}")
        self._peak_spin.setValue(len(self._peaks))
        # Always sync sliders — setValue may not emit if already at same value
        self._active = new_idx
        self._load_peak(new_idx)
        self._redraw_all()

    def _remove_peak(self):
        if not self._peaks:
            return
        idx = self._peak_spin.value() - 1
        self._peaks.pop(idx)
        self._peak_spin.setMaximum(max(1, len(self._peaks)))
        self._peak_count.setText(f"/ {len(self._peaks)}")
        if self._peaks:
            new_idx = min(idx, len(self._peaks) - 1)
            self._active = new_idx
            self._load_peak(new_idx)
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
        self._peak_info.setText(p.get("label") or f"Peak {idx + 1}")
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
        """Redraw the preview: one pseudo-Voigt trace per peak plus their sum.

        Traces are updated in place; only traces beyond the current peak count
        are removed. Colour/width changes (active peak highlight) are applied
        by SpectrumViewer.plot().
        """
        for i in range(len(self._peaks), self._drawn_peak_count):
            self._viewer.remove_plot(f"Peak_{i+1}")

        if self._exp_ppm is None:
            self._viewer.remove_plot("Total Fit")
            self._drawn_peak_count = 0
            return
        ppm = self._exp_ppm
        sfo = self._sl_sfo.value
        total = np.zeros_like(ppm, dtype=float)
        palette = ["#ff7043", "#66bb6a", "#ab47bc", "#ffa726", "#26c6da",
                   "#ec407a", "#9ccc65", "#5c6bc0", "#8d6e63", "#78909c"]
        for i, p in enumerate(self._peaks):
            peak_data = self._preview_scale * p["k"] * pseudo_voigt(
                ppm, p["u"], p["fwhm"], sfo, p["b"], p["phi"])
            total += peak_data
            width = 2.0 if i == self._active else 0.8
            self._viewer.plot(ppm, peak_data, name=f"Peak_{i+1}",
                              color=palette[i % len(palette)], width=width)
        self._viewer.plot(ppm, total, name="Total Fit", color=self._colors["accent"], width=1.5)
        self._drawn_peak_count = len(self._peaks)

    def _save(self):
        self.peaks_modified.emit(self._peaks)

    def update_theme(self, colors: dict):
        self._colors = colors
        self._viewer.update_theme(colors)
        self._redraw_all()  # re-colour the Total Fit trace
