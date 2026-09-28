"""Dashboard — welcome screen with stats cards and quick actions."""

import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QPushButton, QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt


class _StatCard(QFrame):
    """A small card showing a single statistic."""

    def __init__(self, icon: str, value: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(4)

        top = QHBoxLayout()
        ic = QLabel(icon)
        ic.setStyleSheet("font-size: 22px;")
        top.addWidget(ic)
        top.addStretch()
        lay.addLayout(top)

        val = QLabel(value)
        val.setObjectName("stat_value")
        lay.addWidget(val)

        lbl = QLabel(label)
        lbl.setObjectName("stat_label")
        lay.addWidget(lbl)


class DashboardPanel(QWidget):
    """Home screen with quick overview and action buttons."""

    action_requested = Signal(str)  # "new_analysis", "open_input", "batch"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("panel_content")
        root = QVBoxLayout(content)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(24)

        # ── Header ──────────────────────────────────────────
        title = QLabel("Welcome to SpectraFlow")
        title.setObjectName("heading")
        root.addWidget(title)

        subtitle = QLabel(
            "Modern NMR Mixture Analysis  ·  Indirect Hard Modelling  ·  Powered by pyIHM + KLASSEZ"
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # ── Stat cards ──────────────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.addWidget(_StatCard("📂", "0", "Input Files Loaded"))
        cards_row.addWidget(_StatCard("🧪", "0", "Components Ready"))
        cards_row.addWidget(_StatCard("⚡", "—", "Last Fit Duration"))
        cards_row.addWidget(_StatCard("📦", "0", "Batch Jobs Run"))
        root.addLayout(cards_row)

        # ── Quick actions ───────────────────────────────────
        act_title = QLabel("Quick Actions")
        act_title.setObjectName("subheading")
        root.addWidget(act_title)

        acts = QHBoxLayout()
        acts.setSpacing(12)

        for name, icon, label, desc in [
            ("input", "📁", "New Analysis", "Configure input files and fit parameters"),
            ("viewer", "📈", "View Spectrum", "Load and explore NMR spectra interactively"),
            ("fit", "⚡", "Run Fit", "Execute the IHM optimisation on loaded data"),
        ]:
            card = QFrame()
            card.setObjectName("card")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 16, 20, 16)
            cl.setSpacing(8)
            cl.addWidget(QLabel(f"{icon}  {label}", objectName="section_title"))
            d = QLabel(desc)
            d.setObjectName("muted")
            d.setWordWrap(True)
            cl.addWidget(d)
            btn = QPushButton(f"Open {label}")
            btn.setObjectName("action_btn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, n=name: self.action_requested.emit(n))
            cl.addWidget(btn)
            acts.addWidget(card)

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
        sl.setContentsMargins(20, 16, 20, 16)
        sl.setSpacing(6)
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
