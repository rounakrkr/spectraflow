"""Dashboard — welcome screen with stat cards and quick actions."""

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.theme.theme_manager import COLORS
from app.widgets.gradient_label import GradientLabel


class _StatCard(QFrame):
    """A centred card showing a single statistic."""

    def __init__(self, icon: str, value: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 22, 20, 22)
        lay.setSpacing(6)

        ic = QLabel(icon)
        ic.setStyleSheet("font-size: 26px;")
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)

        self.value_label = GradientLabel(value)
        self.value_label.setObjectName("stat_value")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.value_label)

        lbl = QLabel(label.upper())
        lbl.setObjectName("stat_label")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class DashboardPanel(QWidget):
    """Home screen with quick overview and action buttons."""

    action_requested = Signal(str)  # "input", "viewer", "fit"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gradient_labels: list[GradientLabel] = []
        self._build_ui()
        self.update_theme(COLORS["dark"])

    def update_theme(self, colors: dict) -> None:
        """Recolour gradient text to match the active theme palette."""
        start = colors.get("grad_start", "#dbeafe")
        end = colors.get("grad_end", "#60a5fa")
        for label in self._gradient_labels:
            label.set_colors(start, end)

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("panel_content")
        root = QVBoxLayout(content)
        root.setContentsMargins(36, 32, 36, 32)
        root.setSpacing(26)

        # ── Header ──────────────────────────────────────────
        title = GradientLabel("Welcome to SpectraFlow")
        title.setObjectName("heading")
        self._gradient_labels.append(title)
        root.addWidget(title)

        subtitle = QLabel(
            "Modern NMR Mixture Analysis  ·  Indirect Hard Modelling  ·  Powered by pyIHM + KLASSEZ"
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # ── Stat cards ──────────────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(18)
        self._stat_cards = [
            _StatCard("📂", "0", "Input Files Loaded"),
            _StatCard("🧪", "0", "Components Ready"),
            _StatCard("⚡", "—", "Last Fit Duration"),
            _StatCard("📦", "0", "Batch Jobs Run"),
        ]
        for card in self._stat_cards:
            self._gradient_labels.append(card.value_label)
            cards_row.addWidget(card, 1)
        root.addLayout(cards_row)

        # ── Quick actions ───────────────────────────────────
        act_title = QLabel("Quick Actions")
        act_title.setObjectName("subheading")
        root.addWidget(act_title)

        acts = QHBoxLayout()
        acts.setSpacing(18)

        for name, icon, label, desc in [
            ("input", "📁", "New Analysis", "Configure input files and fit parameters"),
            ("viewer", "📈", "View Spectrum", "Load and explore NMR spectra interactively"),
            ("fit", "⚡", "Run Fit", "Execute the IHM optimisation on loaded data"),
        ]:
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(24, 20, 24, 20)
            cl.setSpacing(10)

            card_title = QLabel(f"{icon}  {label}")
            card_title.setObjectName("card_title")
            cl.addWidget(card_title)

            d = QLabel(desc)
            d.setObjectName("muted")
            d.setWordWrap(True)
            d.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            cl.addWidget(d, 1)

            btn = QPushButton(f"Open {label}")
            btn.setObjectName("action_btn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, n=name: self.action_requested.emit(n))
            cl.addWidget(btn)
            acts.addWidget(card, 1)

        root.addLayout(acts)

        # ── Getting started ─────────────────────────────────
        gs_title = QLabel("Getting Started")
        gs_title.setObjectName("subheading")
        root.addWidget(gs_title)

        steps = [
            "1.  Go to Input Config → load your mixture spectrum and component spectra files",
            "2.  Open Spectrum Viewer → inspect your data, verify it loaded correctly",
            "3.  Use Region Selector → pick the spectral windows for fitting",
            "4.  Calibration panel → fine-tune chemical shift drift and intensities",
            "5.  Peak Editor → manually adjust individual peak parameters if needed",
            "6.  Fit Runner → execute the optimisation and monitor convergence live",
            "7.  Results → view concentrations, export figures and CSV data",
        ]
        steps_card = QFrame()
        steps_card.setObjectName("card")
        sl = QVBoxLayout(steps_card)
        sl.setContentsMargins(24, 20, 24, 20)
        sl.setSpacing(8)
        for s in steps:
            lbl = QLabel(s)
            lbl.setWordWrap(True)
            sl.addWidget(lbl)
        root.addWidget(steps_card)

        # ── System info ─────────────────────────────────────
        info = QLabel(f"Python {sys.version.split()[0]}  ·  PySide6  ·  PyQtGraph  ·  NumPy")
        info.setObjectName("muted")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(info)

        root.addStretch()
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
