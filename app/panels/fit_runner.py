"""Fit runner panel — execute the optimisation and monitor live."""

import time
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QProgressBar, QSplitter,
    QTextEdit, QComboBox, QCheckBox,
)
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor, QColor

from ..widgets.spectrum_viewer import SpectrumViewer


class FitRunnerPanel(QWidget):
    """Run the IHM fit with live convergence monitoring."""

    fit_started = Signal()
    fit_finished = Signal(object)      # result dict
    fit_requested = Signal(str)        # method name — wired to engine.run_fit

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._start_time = 0
        self._conv_data: dict[str, list] = {"x": [], "y": []}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_elapsed)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # Header
        tb = QHBoxLayout()
        title = QLabel("Fit Runner")
        title.setObjectName("subheading")
        tb.addWidget(title)
        tb.addStretch()
        root.addLayout(tb)

        # ── Status row ──────────────────────────────────────
        status_card = QFrame()
        status_card.setObjectName("card")
        sl = QHBoxLayout(status_card)
        sl.setContentsMargins(16, 12, 16, 12)
        sl.setSpacing(24)

        self._status_label = QLabel("Ready")
        self._status_label.setObjectName("section_title")
        sl.addWidget(self._status_label)

        self._iter_label = QLabel("Iterations: —")
        self._iter_label.setObjectName("muted")
        sl.addWidget(self._iter_label)

        self._target_label = QLabel("Target: —")
        self._target_label.setObjectName("muted")
        sl.addWidget(self._target_label)

        self._time_label = QLabel("Elapsed: —")
        self._time_label.setObjectName("muted")
        sl.addWidget(self._time_label)

        sl.addStretch()
        root.addWidget(status_card)

        # ── Progress bar ────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate by default
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # ── Control buttons ─────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        # FIX #6: method selector
        btn_row.addWidget(QLabel("Method:"))
        self._method_combo = QComboBox()
        self._method_combo.addItems(["tight", "fast", "custom"])
        self._method_combo.setToolTip("tight = Nelder + leastsq, fast = leastsq only")
        self._method_combo.setMinimumWidth(100)
        btn_row.addWidget(self._method_combo)

        self._align_chk = QCheckBox("Pre-align peaks")
        self._align_chk.setChecked(True)
        self._align_chk.setToolTip("Chemical-shift alignment fit before the main fit (untick = pyihm --noalgn)")
        btn_row.addWidget(self._align_chk)

        self._autosave_chk = QCheckBox("Save outputs after fit")
        self._autosave_chk.setChecked(True)
        self._autosave_chk.setToolTip("Write .out report, -DATA csv and -FIGURES next to the input")
        btn_row.addWidget(self._autosave_chk)

        self._start_btn = QPushButton("▶  Start Fit")
        self._start_btn.setObjectName("primary_btn")
        self._start_btn.setMinimumHeight(44)
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setObjectName("danger_btn")
        self._stop_btn.setMinimumHeight(44)
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── Convergence plot + log ──────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Convergence plot
        conv_frame = QFrame()
        conv_frame.setObjectName("card")
        cf_lay = QVBoxLayout(conv_frame)
        cf_lay.setContentsMargins(8, 8, 8, 8)
        cf_lay.addWidget(QLabel("Convergence", objectName="section_title"))
        self._conv_viewer = SpectrumViewer(show_coords=False)
        self._conv_viewer.set_xlabel("Iteration")
        self._conv_viewer.set_ylabel("log₁₀(Target)")
        self._conv_viewer.plot_widget.invertX(False)  # normal X for convergence
        cf_lay.addWidget(self._conv_viewer)
        splitter.addWidget(conv_frame)

        # Log output
        log_frame = QFrame()
        log_frame.setObjectName("card")
        lf_lay = QVBoxLayout(log_frame)
        lf_lay.setContentsMargins(8, 8, 8, 8)
        lf_lay.addWidget(QLabel("Fit Log", objectName="section_title"))
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Cascadia Code", 10))
        self._log.setObjectName("terminal_output")
        lf_lay.addWidget(self._log)
        splitter.addWidget(log_frame)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

    # ── Options ─────────────────────────────────────────────
    @property
    def align_enabled(self) -> bool:
        return self._align_chk.isChecked()

    @property
    def autosave_enabled(self) -> bool:
        return self._autosave_chk.isChecked()

    # ── Controls ────────────────────────────────────────────
    def _on_start(self):
        self._running = True
        self._start_time = time.time()
        self._start_btn.setVisible(False)
        self._stop_btn.setVisible(True)
        self._progress.setVisible(True)
        self._status_label.setText("⏳ Running…")
        self._log.clear()
        self._conv_data = {"x": [], "y": []}
        self._conv_viewer.clear()
        self._timer.start(1000)
        self.log("Fit started.")
        self.fit_started.emit()
        self.fit_requested.emit(self._method_combo.currentText())  # FIX #6: use selected method

    def _on_stop(self):
        self._running = False
        self._start_btn.setVisible(True)
        self._stop_btn.setVisible(False)
        self._progress.setVisible(False)
        self._status_label.setText("⏹ Stopped")
        self._timer.stop()
        self.log("Fit stopped by user.")

    def _update_elapsed(self):
        elapsed = time.time() - self._start_time
        m, s = divmod(int(elapsed), 60)
        self._time_label.setText(f"Elapsed: {m:02d}:{s:02d}")

    # ── Public API (called by workers) ──────────────────────
    def log(self, text: str, color: str = "#c8d0da"):
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log.setTextCursor(cursor)
        self._log.setTextColor(QColor(color))
        self._log.append(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def update_progress(self, iteration: int, target: float):
        self._iter_label.setText(f"Iterations: {iteration}")
        self._target_label.setText(f"Target: {target:.5e}")
        # Append to convergence plot
        self._conv_data["x"].append(iteration)
        self._conv_data["y"].append(np.log10(target) if target > 0 else -10)
        self._conv_viewer.plot(
            np.array(self._conv_data["x"]),
            np.array(self._conv_data["y"]),
            name="convergence", color="#4fc3f7", width=2,
        )

    def on_fit_complete(self, result=None):
        self._running = False
        self._start_btn.setVisible(True)
        self._stop_btn.setVisible(False)
        self._progress.setVisible(False)
        self._timer.stop()
        self._status_label.setText("✓ Complete")
        elapsed = time.time() - self._start_time
        m, s = divmod(int(elapsed), 60)
        self.log(f"Fit completed in {m:02d}:{s:02d}.", "#66bb6a")
        self.fit_finished.emit(result)

    def update_theme(self, colors: dict):
        self._conv_viewer.update_theme(colors)
