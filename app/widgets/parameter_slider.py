"""
Reusable parameter-slider widget.
Layout:  [Label]  [────slider────]  [spinbox ▲▼] [unit]

The slider is for fast, coarse movement; the spin-box next to it carries
visible ▲/▼ stepper buttons (and ↑/↓, PgUp/PgDn, mouse-wheel) for precise,
repeatable steps of ``step`` size. Typing a value works too.
"""

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QSlider, QDoubleSpinBox, QSizePolicy,
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

        # Label: sized to its text (never clipped); use align_group() to give
        # every row of a form the same label width so the sliders line up.
        self._label = QLabel(label)
        self._label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        lay.addWidget(self._label)

        # Slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(round(self._min * self._internal_scale))
        self._slider.setMaximum(round(self._max * self._internal_scale))
        step_int = max(1, round(self._step * self._internal_scale))
        self._slider.setSingleStep(step_int)
        self._slider.setPageStep(step_int * 10)
        self._slider.setValue(round(default * self._internal_scale))
        self._slider.setMinimumWidth(60)
        self._slider.valueChanged.connect(self._slider_moved)
        lay.addWidget(self._slider, stretch=1)

        # Spinbox with ▲/▼ buttons (styled in the QSS). Width follows the
        # style's size hint for the widest value in range, so text and buttons
        # can't overlap or clip.
        self._spin = QDoubleSpinBox()
        self._spin.setDecimals(self._decimals)
        self._spin.setRange(self._min, self._max)
        self._spin.setSingleStep(self._step)
        self._spin.setValue(default)
        self._spin.setAccelerated(True)          # hold ▲/▼ to speed up
        self._spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._spin.setToolTip(
            f"▲/▼ or ↑/↓: ±{self._step:g}\nPgUp/PgDn or Ctrl+wheel: ±{self._step * 10:g}"
        )
        self._spin.valueChanged.connect(self._spin_changed)
        lay.addWidget(self._spin)

        # Unit (always present, so rows without a unit still align)
        self._unit = QLabel(unit)
        self._unit.setObjectName("muted")
        self._unit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        lay.addWidget(self._unit)

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
        self._slider.setValue(round(val * self._internal_scale))
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
        self._slider.setMinimum(round(min_val * self._internal_scale))
        self._slider.setMaximum(round(max_val * self._internal_scale))
        self._spin.setRange(min_val, max_val)
        self._spin.updateGeometry()

    def set_label(self, text: str):
        self._label.setText(text)

    @property
    def spinbox(self) -> QDoubleSpinBox:
        return self._spin

    # ── Layout helpers ──────────────────────────────────────
    def column_hints(self) -> tuple[int, int, int]:
        """(label, spinbox, unit) natural widths for the current style."""
        return (
            self._label.sizeHint().width(),
            self._spin.sizeHint().width(),
            self._unit.sizeHint().width(),
        )

    def set_column_widths(self, label_w: int, spin_w: int, unit_w: int):
        self._label.setFixedWidth(label_w)
        self._spin.setFixedWidth(spin_w)
        self._unit.setFixedWidth(unit_w)

    @staticmethod
    def align_group(sliders: Iterable["ParameterSlider"]) -> None:
        """Give all sliders the same label / spinbox / unit column widths.

        Each column takes the widest natural width in the group, so no label
        is clipped and every slider track starts and ends at the same x.
        Call again after a theme/font change (sizes come from the stylesheet).
        """
        sliders = list(sliders)
        if not sliders:
            return
        for s in sliders:
            s._spin.ensurePolished()
            s._label.ensurePolished()
        hints = [s.column_hints() for s in sliders]
        label_w = max(h[0] for h in hints)
        spin_w = max(h[1] for h in hints)
        unit_w = max(h[2] for h in hints)
        for s in sliders:
            s.set_column_widths(label_w, spin_w, unit_w)
