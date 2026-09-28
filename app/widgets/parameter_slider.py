"""
Reusable parameter-slider widget.
Layout:  [Label]  [────slider────]  [spinbox] [unit]
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QSlider, QDoubleSpinBox,
)
from PySide6.QtCore import Signal, Qt


class ParameterSlider(QWidget):
    """A labelled slider synced to a spin-box for precise numeric input."""

    value_changed = Signal(float)

    def __init__(
        self,
        label: str = "Param",
        min_val: float = 0.0,
        max_val: float = 1.0,
        default: float = 0.5,
        step: float = 0.01,
        unit: str = "",
        decimals: int = 3,
        parent=None,
    ):
        super().__init__(parent)
        self._min = min_val
        self._max = max_val
        self._step = step
        self._decimals = decimals
        self._internal_scale = 10 ** decimals  # map float → int for QSlider
        self._block = False
        self._build_ui(label, unit, default)

    # ── Build ───────────────────────────────────────────────
    def _build_ui(self, label: str, unit: str, default: float):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(6)

        # Label
        self._label = QLabel(label)
        self._label.setMinimumWidth(50)
        self._label.setMaximumWidth(80)
        self._label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._label)

        # Slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(int(self._min * self._internal_scale))
        self._slider.setMaximum(int(self._max * self._internal_scale))
        self._slider.setSingleStep(int(self._step * self._internal_scale))
        self._slider.setValue(int(default * self._internal_scale))
        self._slider.setMinimumWidth(80)
        self._slider.valueChanged.connect(self._slider_moved)
        lay.addWidget(self._slider, stretch=1)

        # Spinbox
        self._spin = QDoubleSpinBox()
        self._spin.setDecimals(self._decimals)
        self._spin.setRange(self._min, self._max)
        self._spin.setSingleStep(self._step)
        self._spin.setValue(default)
        self._spin.setFixedWidth(75)
        self._spin.valueChanged.connect(self._spin_changed)
        lay.addWidget(self._spin)

        # Unit
        if unit:
            u_label = QLabel(unit)
            u_label.setObjectName("muted")
            u_label.setFixedWidth(30)
            lay.addWidget(u_label)

    # ── Sync ────────────────────────────────────────────────
    def _slider_moved(self, int_val: int):
        if self._block:
            return
        self._block = True
        val = int_val / self._internal_scale
        self._spin.setValue(val)
        self.value_changed.emit(val)
        self._block = False

    def _spin_changed(self, val: float):
        if self._block:
            return
        self._block = True
        self._slider.setValue(int(val * self._internal_scale))
        self.value_changed.emit(val)
        self._block = False

    # ── Public API ──────────────────────────────────────────
    @property
    def value(self) -> float:
        return self._spin.value()

    @value.setter
    def value(self, v: float):
        self._spin.setValue(v)

    def set_range(self, min_val: float, max_val: float):
        self._min = min_val
        self._max = max_val
        self._slider.setMinimum(int(min_val * self._internal_scale))
        self._slider.setMaximum(int(max_val * self._internal_scale))
        self._spin.setRange(min_val, max_val)

    def set_label(self, text: str):
        self._label.setText(text)
