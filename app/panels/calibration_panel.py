"""Calibration panel — adjust chemical-shift drift and intensity per component."""

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QComboBox, QSplitter, QCheckBox,
)
from PySide6.QtCore import Signal, Qt

from ..widgets.spectrum_viewer import SpectrumViewer
from ..widgets.parameter_slider import ParameterSlider


# Per-component colors
COMP_COLORS = [
    "#ff7043", "#66bb6a", "#ab47bc", "#ffa726",
    "#26c6da", "#ec407a", "#9ccc65", "#5c6bc0",
    "#8d6e63", "#78909c",
]


class CalibrationPanel(QWidget):
    """Calibrate chemical-shift drift and intensity of each component spectrum."""

    # Signal(object), not Signal(dict): Qt's dict converter silently drops int-keyed dicts.
    calibration_done = Signal(object)  # {comp_idx: {"drift": float, "intensity": float}}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._components: list[dict] = []   # [{name, ppm, data, drift, intensity}]
        self._active_idx = 0
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # Header
        tb = QHBoxLayout()
        title = QLabel("Calibration")
        title.setObjectName("subheading")
        tb.addWidget(title)
        tb.addStretch()

        self._write_cal_chk = QCheckBox("Write -cal.fvf files")
        self._write_cal_chk.setChecked(True)
        self._write_cal_chk.setToolTip("Save calibrated copies of the component files next to the originals")
        tb.addWidget(self._write_cal_chk)

        reset_btn = QPushButton("↺ Reset All")
        reset_btn.clicked.connect(self._reset_all)
        tb.addWidget(reset_btn)

        save_btn = QPushButton("💾 Save Calibration")
        save_btn.setObjectName("primary_btn")
        save_btn.clicked.connect(self._save)
        tb.addWidget(save_btn)

        root.addLayout(tb)

        hint = QLabel("Select a component, then use sliders to adjust its chemical-shift drift and intensity. "
                       "Changes are reflected live in the plot.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── Main splitter: plot | controls ──────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._viewer = SpectrumViewer()
        splitter.addWidget(self._viewer)

        # Controls panel
        ctrl = QWidget()
        cl = QVBoxLayout(ctrl)
        cl.setContentsMargins(12, 0, 0, 0)
        cl.setSpacing(12)

        cl.addWidget(QLabel("Active Component", objectName="section_title"))
        self._comp_combo = QComboBox()
        self._comp_combo.currentIndexChanged.connect(self._on_comp_changed)
        cl.addWidget(self._comp_combo)

        # Sliders
        cal_card = QFrame()
        cal_card.setObjectName("card")
        card_lay = QVBoxLayout(cal_card)
        card_lay.setContentsMargins(12, 12, 12, 12)
        card_lay.setSpacing(8)

        card_lay.addWidget(QLabel("Chemical Shift Drift", objectName="section_title"))
        self._drift_slider = ParameterSlider("δ drift", -0.5, 0.5, 0.0, 0.001, "ppm", 4)
        self._drift_slider.value_changed.connect(self._on_drift)
        card_lay.addWidget(self._drift_slider)

        card_lay.addWidget(QLabel("Intensity Correction", objectName="section_title"))
        self._int_slider = ParameterSlider("I factor", 0.0, 5.0, 1.0, 0.01, "×", 3)
        self._int_slider.value_changed.connect(self._on_intensity)
        card_lay.addWidget(self._int_slider)

        cl.addWidget(cal_card)
        self._sliders = [self._drift_slider, self._int_slider]
        ParameterSlider.align_group(self._sliders)

        # Per-component summary
        cl.addWidget(QLabel("All Components", objectName="section_title"))
        self._summary = QLabel("No components loaded.")
        self._summary.setObjectName("muted")
        self._summary.setWordWrap(True)
        cl.addWidget(self._summary)

        cl.addStretch()
        ctrl.setMinimumWidth(400)
        splitter.addWidget(ctrl)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)
        splitter.setCollapsible(1, False)
        splitter.setSizes([900, 420])

        root.addWidget(splitter, stretch=1)

    # ── Data loading ────────────────────────────────────────
    def set_experimental(self, ppm: np.ndarray, data: np.ndarray):
        self._viewer.plot(ppm, data, name="Experimental", color="#e4e8ee", width=1.2)

    def add_component(self, name: str, ppm: np.ndarray, data: np.ndarray):
        idx = len(self._components)
        color = COMP_COLORS[idx % len(COMP_COLORS)]
        self._components.append({
            "name": name, "ppm": ppm, "data": data.copy(), "data_orig": data.copy(),
            "drift": 0.0, "intensity": 1.0, "color": color,
        })
        self._comp_combo.addItem(f"{idx+1}. {name}")
        self._viewer.plot(ppm, data, name=name, color=color, width=1.0)
        self._update_summary()

    def clear_components(self):
        """Drop every loaded component (keeps the experimental trace).

        Called before a (re)load so repeated loads replace, not stack.
        """
        for comp in self._components:
            self._viewer.remove_plot(comp["name"])
        self._components.clear()
        self._active_idx = 0
        self._comp_combo.blockSignals(True)
        self._comp_combo.clear()
        self._comp_combo.blockSignals(False)
        for sl, v in ((self._drift_slider, 0.0), (self._int_slider, 1.0)):
            sl.blockSignals(True)
            sl.value = v
            sl.blockSignals(False)
        self._update_summary()

    def clear_all(self):
        """Components and the experimental trace (new mixture loaded)."""
        self.clear_components()
        self._viewer.remove_plot("Experimental")

    def showEvent(self, event):
        super().showEvent(event)
        ParameterSlider.align_group(self._sliders)   # sizes depend on the active theme

    @property
    def write_cal_files(self) -> bool:
        return self._write_cal_chk.isChecked()

    # ── Slots ───────────────────────────────────────────────
    def _on_comp_changed(self, idx):
        if 0 <= idx < len(self._components):
            self._active_idx = idx
            c = self._components[idx]
            self._drift_slider.value = c["drift"]
            self._int_slider.value = c["intensity"]

    def _on_drift(self, val):
        if not self._components:
            return
        c = self._components[self._active_idx]
        c["drift"] = val
        self._redraw_component(self._active_idx)

    def _on_intensity(self, val):
        if not self._components:
            return
        c = self._components[self._active_idx]
        c["intensity"] = val
        self._redraw_component(self._active_idx)

    def _redraw_component(self, idx):
        c = self._components[idx]
        shifted_ppm = c["ppm"] + c["drift"]
        scaled_data = c["data_orig"] * c["intensity"]
        self._viewer.plot(shifted_ppm, scaled_data, name=c["name"], color=c["color"], width=1.0)
        self._update_summary()

    def _reset_all(self):
        for i, c in enumerate(self._components):
            c["drift"] = 0.0
            c["intensity"] = 1.0
            self._redraw_component(i)
        if self._components:
            self._drift_slider.value = 0.0
            self._int_slider.value = 1.0

    def _save(self):
        result = {}
        for i, c in enumerate(self._components):
            result[i] = {"drift": c["drift"], "intensity": c["intensity"]}
        self.calibration_done.emit(result)

    def _update_summary(self):
        lines = []
        for i, c in enumerate(self._components):
            marker = "▸" if i == self._active_idx else "  "
            lines.append(f"{marker} {i+1}. {c['name']}:  Δδ={c['drift']:+.4f} ppm,  I×{c['intensity']:.3f}")
        self._summary.setText("\n".join(lines) if lines else "No components loaded.")

    def update_theme(self, colors: dict):
        self._viewer.update_theme(colors)
