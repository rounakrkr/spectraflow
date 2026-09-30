"""Input configuration panel — load files, set fit parameters."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QComboBox, QCheckBox,
    QRadioButton, QButtonGroup, QListWidget, QListWidgetItem,
    QFileDialog, QAbstractItemView,
)
from PySide6.QtCore import Signal, Qt

from ..widgets.file_browser import FileBrowser
from ..widgets.parameter_slider import ParameterSlider


class InputConfigPanel(QWidget):
    """Configure input files, processing options, and fit parameters."""

    config_ready = Signal(dict)          # Emitted with the complete config dict
    input_file_loaded = Signal(str)      # Emitted with path to a pyihm .inp file

    def __init__(self, parent=None):
        super().__init__(parent)
        self._comp_paths: list[str] = []
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("panel_content")
        root = QVBoxLayout(content)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(20)

        title = QLabel("Input Configuration")
        title.setObjectName("heading")
        root.addWidget(title)
        root.addWidget(QLabel("Load your spectra, set processing options, and define fit boundaries.", objectName="muted"))

        # ── Quick load: pyihm input file ────────────────────
        inp_row = QHBoxLayout()
        inp_btn = QPushButton("📄 Load pyihm Input File (.inp)")
        inp_btn.setObjectName("primary_btn")
        inp_btn.setToolTip("Load a traditional pyihm input text file — auto-fills all fields")
        inp_btn.clicked.connect(self._load_input_file)
        inp_row.addWidget(inp_btn)
        inp_row.addStretch()
        root.addLayout(inp_row)

        sep = QLabel("— or configure manually below —")
        sep.setObjectName("muted")
        sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(sep)

        # ── Section 1: Mixture Spectrum ─────────────────────
        root.addWidget(self._section_header("1. Mixture Spectrum"))
        self._mix_browser = FileBrowser(
            label="",
            mode="file",
            file_filter="NMR Data (*.fid *.ser *.1r *.txt);;All Files (*)",
            placeholder="Select mixture spectrum file…",
        )
        root.addWidget(self._mix_browser)

        # ── Section 2: Component Spectra ────────────────────
        root.addWidget(self._section_header("2. Component Spectra"))

        desc = QLabel("Add individual component .fvf files, or browse a folder to load all at once.")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        root.addWidget(desc)

        comp_row = QHBoxLayout()
        comp_row.setSpacing(8)
        add_btn = QPushButton("+ Add Files")
        add_btn.clicked.connect(self._add_comp_files)
        comp_row.addWidget(add_btn)

        folder_btn = QPushButton("📁 Browse Folder")
        folder_btn.clicked.connect(self._add_comp_folder)
        comp_row.addWidget(folder_btn)

        clear_btn = QPushButton("✗ Clear All")
        clear_btn.setObjectName("danger_btn")
        clear_btn.clicked.connect(self._clear_comps)
        comp_row.addWidget(clear_btn)
        comp_row.addStretch()
        root.addLayout(comp_row)

        self._comp_list = QListWidget()
        self._comp_list.setMaximumHeight(140)
        self._comp_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        root.addWidget(self._comp_list)

        # ── Section 3: Processing Options ───────────────────
        root.addWidget(self._section_header("3. Processing Options"))
        proc_card = QFrame()
        proc_card.setObjectName("card")
        pl = QVBoxLayout(proc_card)
        pl.setContentsMargins(16, 12, 16, 12)
        pl.setSpacing(10)

        # Window function
        wf_row = QHBoxLayout()
        wf_row.addWidget(QLabel("Window Function:"))
        self._wf_combo = QComboBox()
        self._wf_combo.addItems(["None", "Exponential", "Gaussian", "Sine-Bell", "QSIN"])
        wf_row.addWidget(self._wf_combo)
        wf_row.addStretch()
        pl.addLayout(wf_row)

        checks_row = QHBoxLayout()
        self._chk_zf = QCheckBox("Zero-Fill")
        self._chk_blp = QCheckBox("Baseline Correction")
        self._chk_phase = QCheckBox("Auto Phase")
        self._chk_pknl = QCheckBox("PKNL")
        checks_row.addWidget(self._chk_zf)
        checks_row.addWidget(self._chk_blp)
        checks_row.addWidget(self._chk_phase)
        checks_row.addWidget(self._chk_pknl)
        checks_row.addStretch()
        pl.addLayout(checks_row)

        root.addWidget(proc_card)

        # ── Section 4: Fit Boundaries ───────────────────────
        root.addWidget(self._section_header("4. Fit Parameter Boundaries"))
        bounds_card = QFrame()
        bounds_card.setObjectName("card")
        bl = QVBoxLayout(bounds_card)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(6)

        self._utol = ParameterSlider("δ tolerance", 0.0, 1.0, 0.2, 0.01, "ppm", 2)
        self._utol_sg = ParameterSlider("δ tol (group)", 0.0, 0.5, 0.1, 0.005, "ppm", 3)
        self._stol = ParameterSlider("Linewidth tol", 0.0, 50.0, 10.0, 0.5, "Hz", 1)
        self._ktol = ParameterSlider("Intensity tol", 0.0, 0.1, 0.01, 0.001, "×", 3)

        bl.addWidget(self._utol)
        bl.addWidget(self._utol_sg)
        bl.addWidget(self._stol)
        bl.addWidget(self._ktol)
        root.addWidget(bounds_card)

        # ── Section 5: Fit Method ───────────────────────────
        root.addWidget(self._section_header("5. Optimisation Method"))
        method_card = QFrame()
        method_card.setObjectName("card")
        ml = QHBoxLayout(method_card)
        ml.setContentsMargins(16, 12, 16, 12)
        ml.setSpacing(16)

        self._method_group = QButtonGroup(self)
        for i, (text, tip) in enumerate([
            ("Fast (Levenberg-Marquardt)", "Single pass, quick convergence"),
            ("Tight (Nelder-Mead → L-M)", "Two-pass, higher accuracy"),
            ("Custom", "Define your own multi-pass strategy"),
        ]):
            rb = QRadioButton(text)
            rb.setToolTip(tip)
            if i == 1:
                rb.setChecked(True)
            self._method_group.addButton(rb, i)
            ml.addWidget(rb)
        ml.addStretch()
        root.addWidget(method_card)

        # ── Load / Save ─────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        load_btn = QPushButton("📄 Load pyIHM Input File")
        load_btn.clicked.connect(self._load_input_file)
        btn_row.addWidget(load_btn)

        save_btn = QPushButton("💾 Save Configuration")
        save_btn.setObjectName("primary_btn")
        save_btn.clicked.connect(self._save_config)
        btn_row.addWidget(save_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        root.addStretch()
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Helpers ─────────────────────────────────────────────
    @staticmethod
    def _section_header(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("subheading")
        return lbl

    def _add_comp_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add Component Files", "",
            "Voigt Files (*.fvf);;All Files (*)",
        )
        for p in paths:
            if p not in self._comp_paths:
                self._comp_paths.append(p)
                self._comp_list.addItem(QListWidgetItem(p))

    def _add_comp_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Components Folder")
        if folder:
            import os
            # Only add known NMR / spectrum file types
            valid_exts = {".fvf", ".ft", ".1r", ".fid", ".txt", ".csv", ".dat", ".dx", ".jdx"}
            for f in sorted(os.listdir(folder)):
                full = os.path.join(folder, f)
                _, ext = os.path.splitext(f)
                if os.path.isfile(full) and ext.lower() in valid_exts and full not in self._comp_paths:
                    self._comp_paths.append(full)
                    self._comp_list.addItem(QListWidgetItem(full))

    def _clear_comps(self):
        self._comp_paths.clear()
        self._comp_list.clear()

    def _load_input_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open pyIHM Input File", "",
            "Input Files (pyihm_input*);;All Files (*)",
        )
        if path:
            # TODO: parse with pyihm.input_reading and populate fields
            pass

    def _build_config(self) -> dict:
        """Build the full configuration dict — single source of truth."""
        methods = ["fast", "tight", "custom"]
        return {
            "mix_path": self._mix_browser.get_path(),
            "comp_paths": list(self._comp_paths),
            "proc": {
                "wf": self._wf_combo.currentText().lower(),
                "zf": self._chk_zf.isChecked(),
                "blp": self._chk_blp.isChecked(),
                "phase": self._chk_phase.isChecked(),
                "pknl": self._chk_pknl.isChecked(),
            },
            "bounds": {
                "utol": self._utol.value,
                "utol_sg": self._utol_sg.value,
                "stol": self._stol.value,
                "ktol": self._ktol.value,
            },
            "method": methods[self._method_group.checkedId()],
        }

    def _save_config(self):
        config = self._build_config()
        self.config_ready.emit(config)

    def get_config(self) -> dict:
        """Programmatic access to current configuration."""
        return self._build_config()

    def _load_input_file(self):
        """Open a pyihm input file (.inp / .txt) and emit its path."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load pyihm Input File",
            "",
            "pyihm Input (*.inp *.txt);;All Files (*)",
        )
        if path:
            self.input_file_loaded.emit(path)
