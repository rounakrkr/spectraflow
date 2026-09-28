"""Batch processor — run multiple IHM fits in parallel."""

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from PySide6.QtCore import QThread, Signal, QObject


class BatchSignals(QObject):
    """Signals emitted by the batch processor."""
    job_completed = Signal(int, object)     # job_index, result
    batch_finished = Signal(list)           # all results
    progress = Signal(int, int)             # completed, total
    error = Signal(int, str)                # job_index, message
    log = Signal(str)


class BatchProcessor(QThread):
    """Run N independent IHM fits in parallel using multiprocessing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = BatchSignals()
        self._input_files: list[str] = []
        self._n_workers: int | None = None
        self._fit_fn = None

    def configure(self, input_files: list[str], fit_fn=None, n_workers: int | None = None):
        """Set up the batch before calling start()."""
        self._input_files = list(input_files)
        self._fit_fn = fit_fn
        self._n_workers = n_workers or max(1, (os.cpu_count() or 4) - 1)

    def run(self):
        results = [None] * len(self._input_files)
        total = len(self._input_files)
        completed = 0

        self.signals.log.emit(
            f"Starting batch: {total} jobs on {self._n_workers} workers."
        )

        if self._fit_fn is None:
            self.signals.log.emit("No fit function provided — nothing to do.")
            self.signals.batch_finished.emit(results)
            return

        try:
            with ProcessPoolExecutor(max_workers=self._n_workers) as pool:
                futures = {
                    pool.submit(self._fit_fn, path): idx
                    for idx, path in enumerate(self._input_files)
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        res = future.result()
                        results[idx] = res
                        self.signals.job_completed.emit(idx, res)
                    except Exception as e:
                        self.signals.error.emit(idx, str(e))
                    completed += 1
                    self.signals.progress.emit(completed, total)
        except Exception as e:
            self.signals.log.emit(f"Batch error: {e}")

        self.signals.batch_finished.emit(results)
        self.signals.log.emit("Batch processing complete.")
