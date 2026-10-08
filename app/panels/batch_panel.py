"""Batch panel — run one template input over many mixtures, or many input files."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QLineEdit, QRadioButton, QButtonGroup, QStackedWidget, QComboBox, QCheckBox,
    QSpinBox, QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QMessageBox,
)

from ..core import batch_jobs, exporter
from ..core.batch_processor import BatchProcessor

MODE_TEMPLATE, MODE_FILES = 0, 1

COL_JOB, COL_STATUS, COL_CONC, COL_TIME = range(4)

STATUS_COLORS = {
    "done": "#66bb6a",
    "failed": "#ef5350",
    "cancelled": "#fbbf24",
}


class BatchPanel(QWidget):
    """Queue many fits, watch them run in parallel, export one summary table."""

    exported = Signal(str)
    log = Signal(str)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mixtures: list[str] = []
        self._inp_files: list[str] = []
        self._rows: list[dict] = []
        self._proc: BatchProcessor | None = None
        self._abort_message = ""
        self._build_ui()
        self._refresh_table()

    # ── Build ───────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        title = QLabel("Batch Processing")
        title.setObjectName("subheading")
        root.addWidget(title)

        self._setup_card = QFrame()
        self._setup_card.setObjectName("card")
        setup = QVBoxLayout(self._setup_card)
        setup.setContentsMargins(16, 12, 16, 12)
        setup.setSpacing(10)

        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        for mode, text in ((MODE_TEMPLATE, "Template input + mixtures folder"),
                           (MODE_FILES, "Separate input files")):
            radio = QRadioButton(text)
            self._mode_group.addButton(radio, mode)
            mode_row.addWidget(radio)
        self._mode_group.button(MODE_TEMPLATE).setChecked(True)
        mode_row.addStretch()
        setup.addLayout(mode_row)

        self._mode_stack = QStackedWidget()
        self._mode_stack.addWidget(self._build_template_page())
        self._mode_stack.addWidget(self._build_files_page())
        setup.addWidget(self._mode_stack)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output folder"))
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText("Default: next to the mixtures folder / first input")
        out_row.addWidget(self._out_edit, stretch=1)
        out_btn = QPushButton("Browse…")
        out_btn.clicked.connect(self._browse_out_dir)
        out_row.addWidget(out_btn)
        setup.addLayout(out_row)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(12)
        opt_row.addWidget(QLabel("Method"))
        self._method = QComboBox()
        self._method.addItems(["tight", "fast", "custom"])
        self._method.setToolTip("tight = Nelder + leastsq, fast = leastsq only, custom = fit_kws of the input file")
        opt_row.addWidget(self._method)
        self._align = QCheckBox("Pre-align peaks")
        self._align.setChecked(True)
        opt_row.addWidget(self._align)
        opt_row.addWidget(QLabel("Workers"))
        self._workers = QSpinBox()
        cpus = os.cpu_count() or 2
        self._workers.setRange(1, cpus)
        self._workers.setValue(max(1, cpus - 1))
        opt_row.addWidget(self._workers)
        opt_row.addStretch()
        setup.addLayout(opt_row)

        self._mode_group.idClicked.connect(self._on_mode_changed)
        root.addWidget(self._setup_card)

        run_row = QHBoxLayout()
        run_row.setSpacing(12)
        self._run_btn = QPushButton("▶  Run Batch")
        self._run_btn.setObjectName("primary_btn")
        self._run_btn.setMinimumHeight(40)
        self._run_btn.clicked.connect(self._on_run)
        run_row.addWidget(self._run_btn)

        self._cancel_btn = QPushButton("■  Cancel")
        self._cancel_btn.setObjectName("danger_btn")
        self._cancel_btn.setMinimumHeight(40)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        run_row.addWidget(self._cancel_btn)

        self._remove_btn = QPushButton("Remove selected")
        self._remove_btn.clicked.connect(self._remove_selected)
        run_row.addWidget(self._remove_btn)

        run_row.addStretch()
        self._export_btn = QPushButton("📄 Summary CSV")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_summary)
        run_row.addWidget(self._export_btn)
        root.addLayout(run_row)

        progress_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        progress_row.addWidget(self._progress, stretch=1)
        self._progress_label = QLabel("No jobs")
        self._progress_label.setObjectName("muted")
        progress_row.addWidget(self._progress_label)
        root.addLayout(progress_row)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Mixture / job", "Status", "Concentrations", "Time"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(COL_JOB, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_CONC, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_TIME, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        root.addWidget(self._table, stretch=1)

    def _build_template_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)

        grid.addWidget(QLabel("Template input"), 0, 0)
        self._template_edit = QLineEdit()
        self._template_edit.setPlaceholderText("pyihm .inp with the components, regions and boundaries to reuse")
        grid.addWidget(self._template_edit, 0, 1)
        template_btn = QPushButton("Browse…")
        template_btn.clicked.connect(self._browse_template)
        grid.addWidget(template_btn, 0, 2)

        grid.addWidget(QLabel("Mixtures folder"), 1, 0)
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setPlaceholderText("Folder holding one dataset per mixture")
        grid.addWidget(self._folder_edit, 1, 1)
        folder_btn = QPushButton("Browse…")
        folder_btn.clicked.connect(self._browse_mixtures)
        grid.addWidget(folder_btn, 1, 2)

        grid.setColumnStretch(1, 1)
        return page

    def _build_files_page(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        add_btn = QPushButton("Add input files…")
        add_btn.clicked.connect(self._add_input_files)
        row.addWidget(add_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_inputs)
        row.addWidget(clear_btn)
        hint = QLabel("Each input file is one job and uses its own mixture and settings.")
        hint.setObjectName("muted")
        row.addWidget(hint)
        row.addStretch()
        return page

    # ── Public API ──────────────────────────────────────────
    def set_template(self, path: str):
        """Prefill the template with the input file loaded elsewhere, if none is set."""
        if path and not self._template_edit.text().strip():
            self._template_edit.setText(path)

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.isRunning()

    def shutdown(self):
        """Stop a running batch before the application closes."""
        if self.is_running():
            self._proc.cancel()
            self._proc.wait(10000)

    # ── Selection ───────────────────────────────────────────
    @property
    def _mode(self) -> int:
        return self._mode_group.checkedId()

    def _selection(self) -> list[str]:
        return self._mixtures if self._mode == MODE_TEMPLATE else self._inp_files

    def _on_mode_changed(self, mode: int):
        self._mode_stack.setCurrentIndex(mode)
        self._refresh_table()

    def _browse_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Template pyihm Input File", "", "pyihm Input (*.inp *.txt);;All Files (*)")
        if path:
            self._template_edit.setText(path)

    def _browse_mixtures(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Mixtures Folder")
        if not folder:
            return
        out_dir = self._out_edit.text().strip()
        found = batch_jobs.discover_mixtures(folder, exclude=(out_dir,) if out_dir else ())
        self._folder_edit.setText(folder)
        self._mixtures = found
        if not out_dir:
            self._out_edit.setText(os.path.abspath(folder).rstrip("\\/") + "-results")
        self._refresh_table()
        self.log.emit(f"Batch: {len(found)} mixture(s) found in {folder}")

    def _add_input_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add pyihm Input Files", "", "pyihm Input (*.inp *.txt);;All Files (*)")
        known = set(self._inp_files)
        self._inp_files += [p for p in paths if p not in known]
        self._refresh_table()

    def _clear_inputs(self):
        self._inp_files.clear()
        self._refresh_table()

    def _browse_out_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self._out_edit.setText(folder)

    def _remove_selected(self):
        rows = sorted({i.row() for i in self._table.selectedIndexes()}, reverse=True)
        items = self._selection()
        for row in rows:
            if row < len(items):
                del items[row]
        self._refresh_table()

    # ── Table ───────────────────────────────────────────────
    def _refresh_table(self):
        names = [os.path.basename(os.path.normpath(p)) for p in self._selection()]
        self._rows = [{"label": n, "status": "queued"} for n in names]
        self._table.setRowCount(len(names))
        for i, name in enumerate(names):
            self._set_row(i, name, "Queued")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress_label.setText(f"{len(names)} job(s)" if names else "No jobs")
        self._export_btn.setEnabled(False)

    def _set_row(self, idx: int, job: str, status: str, conc: str = "",
                 elapsed: str = "", tip: str = "", color: str | None = None):
        for col, text in ((COL_JOB, job), (COL_STATUS, status), (COL_CONC, conc), (COL_TIME, elapsed)):
            item = self._table.item(idx, col) or QTableWidgetItem()
            item.setText(text)
            item.setToolTip(tip)
            if col == COL_STATUS and color:
                item.setForeground(QColor(color))
            self._table.setItem(idx, col, item)

    # ── Run ─────────────────────────────────────────────────
    def _default_out_dir(self) -> str:
        if self._mode == MODE_TEMPLATE and self._folder_edit.text():
            return os.path.abspath(self._folder_edit.text()).rstrip("\\/") + "-results"
        first = os.path.dirname(os.path.abspath(self._inp_files[0]))
        return os.path.join(first, "batch-results")

    def _on_run(self):
        if self.is_running():
            return
        items = self._selection()
        if not items:
            QMessageBox.information(self, "Batch", "Add mixtures or input files first.")
            return

        template = self._template_edit.text().strip()
        if self._mode == MODE_TEMPLATE and not os.path.isfile(template):
            QMessageBox.warning(self, "Batch", "Select a valid template input file.")
            return

        out_dir = self._out_edit.text().strip() or self._default_out_dir()
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Batch", f"Cannot create the output folder:\n{e}")
            return
        self._out_edit.setText(out_dir)

        if self._mode == MODE_TEMPLATE:
            jobs = batch_jobs.build_template_jobs(template, items, out_dir)
        else:
            jobs = batch_jobs.build_input_file_jobs(items, out_dir)

        self._refresh_table()
        self._abort_message = ""

        proc = BatchProcessor(self)
        proc.configure(
            jobs,
            fit_fn=batch_jobs.batch_fit_fn(self._method.currentText(), self._align.isChecked()),
            n_workers=self._workers.value(),
        )
        proc.signals.job_completed.connect(self._on_job_done)
        proc.signals.error.connect(self._on_job_error)
        proc.signals.progress.connect(self._on_progress)
        proc.signals.log.connect(self.log)
        proc.signals.batch_finished.connect(self._on_batch_finished)
        proc.finished.connect(self._on_thread_finished)
        proc.finished.connect(proc.deleteLater)
        self._proc = proc

        self._progress.setRange(0, len(jobs))
        self._progress.setValue(0)
        self._progress_label.setText(f"0 / {len(jobs)}")
        self._set_running(True)
        proc.start()

    def _on_cancel(self):
        if self._proc is not None:
            self._proc.cancel()
            self._cancel_btn.setEnabled(False)
            self._progress_label.setText("Cancelling…")

    def _set_running(self, running: bool):
        self._setup_card.setEnabled(not running)
        self._run_btn.setVisible(not running)
        self._remove_btn.setEnabled(not running)
        self._cancel_btn.setVisible(running)
        self._cancel_btn.setEnabled(running)

    # ── Batch events ────────────────────────────────────────
    def _on_job_done(self, idx: int, summary: dict):
        self._rows[idx] = {
            "label": summary["label"], "status": "done",
            "component_names": summary["component_names"],
            "concentrations": summary["concentrations"],
            "nfev": summary["nfev"], "elapsed": summary["elapsed"],
            "message": summary["message"],
        }
        conc = "  ·  ".join(
            f"{n} {c * 100:.2f}%"
            for n, c in zip(summary["component_names"], summary["concentrations"])
        )
        self._set_row(idx, summary["label"], "✅ Done", conc, f"{summary['elapsed']:.1f} s",
                      tip=summary["out_root"], color=STATUS_COLORS["done"])

    def _on_job_error(self, idx: int, message: str):
        if idx < 0:
            self._abort_message = message
            self.error.emit(message)
            return
        label = self._rows[idx]["label"]
        self._rows[idx] = {"label": label, "status": "failed", "message": message}
        self._set_row(idx, label, "❌ Failed", message.splitlines()[0] if message else "",
                      tip=message, color=STATUS_COLORS["failed"])
        self.error.emit(f"[batch] {label}: {message}")

    def _on_progress(self, done: int, total: int):
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._progress_label.setText(f"{done} / {total}")

    def _on_batch_finished(self, _results: list):
        for idx, row in enumerate(self._rows):
            if row["status"] != "queued":
                continue
            if self._abort_message:
                row.update(status="failed", message=self._abort_message)
                self._set_row(idx, row["label"], "❌ Failed", self._abort_message,
                              tip=self._abort_message, color=STATUS_COLORS["failed"])
            else:
                row["status"] = "cancelled"
                self._set_row(idx, row["label"], "⏹ Cancelled", color=STATUS_COLORS["cancelled"])
        self._export_btn.setEnabled(any(r["status"] in ("done", "failed") for r in self._rows))

    def _on_thread_finished(self):
        self._proc = None
        self._set_running(False)

    # ── Export ──────────────────────────────────────────────
    def _export_summary(self):
        start = os.path.join(self._out_edit.text().strip(), "batch-summary.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Save Batch Summary", start, "CSV (*.csv)")
        if not path:
            return
        try:
            exporter.write_batch_summary(path, self._rows)
        except OSError as e:
            QMessageBox.warning(self, "Summary CSV", str(e))
            return
        self.exported.emit(f"Exported {path}")
