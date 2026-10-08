"""Batch processor — run multiple IHM fits in parallel."""

import os
import pickle
import threading
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from PySide6.QtCore import QThread, Signal, QObject

from app.core.batch_jobs import init_worker, worker_environ


class BatchSignals(QObject):
    """Signals emitted by the batch processor."""
    job_completed = Signal(int, object)     # job_index, result
    batch_finished = Signal(list)           # all results (None for failed/cancelled jobs)
    progress = Signal(int, int)             # completed, total
    error = Signal(int, str)                # job_index (-1 = batch-level), message
    log = Signal(str)


class BatchProcessor(QThread):
    """Run N independent IHM fits in parallel using multiprocessing.

    ``fit_fn`` runs in a worker *process*, so it must be picklable: a
    module-level function (or ``functools.partial`` of one), not a lambda or
    nested function. This is checked up-front so the failure is one clear
    message instead of one opaque error per job.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = BatchSignals()
        self._input_files: list[str] = []
        self._n_workers: int | None = None
        self._fit_fn = None
        self._cancel = threading.Event()

    def configure(self, input_files: list[str], fit_fn=None, n_workers: int | None = None):
        """Set up the batch before calling start().

        Each item of ``input_files`` is passed to ``fit_fn`` as-is: a path, or
        any picklable job object (see :class:`app.core.batch_jobs.BatchJob`).
        """
        self._input_files = list(input_files)
        self._fit_fn = fit_fn
        self._n_workers = n_workers or max(1, (os.cpu_count() or 4) - 1)
        self._cancel.clear()

    def cancel(self):
        """Stop submitting work; queued jobs are dropped, running jobs finish."""
        self._cancel.set()

    def run(self):
        total = len(self._input_files)
        results = [None] * total
        failed = 0
        completed = 0

        if self._fit_fn is None:
            self.signals.log.emit("No fit function provided — nothing to do.")
            self.signals.batch_finished.emit(results)
            return

        try:
            pickle.dumps(self._fit_fn)
        except Exception as e:
            msg = (f"fit_fn cannot be sent to worker processes ({e}). "
                   "Use a module-level function instead of a lambda or nested function.")
            self.signals.error.emit(-1, msg)
            self.signals.log.emit(f"Batch aborted: {msg}")
            self.signals.batch_finished.emit(results)
            return

        self.signals.log.emit(
            f"Starting batch: {total} jobs on {self._n_workers} workers."
        )

        with worker_environ():
            pending: dict = {}
            pool = ProcessPoolExecutor(
                max_workers=self._n_workers, initializer=init_worker
            )
            try:
                pending = {pool.submit(self._fit_fn, path): idx
                           for idx, path in enumerate(self._input_files)}
                while pending:
                    if self._cancel.is_set():
                        break
                    done, _ = wait(list(pending), timeout=0.2, return_when=FIRST_COMPLETED)
                    for future in done:
                        idx = pending.pop(future)
                        try:
                            res = future.result()
                            results[idx] = res
                            self.signals.job_completed.emit(idx, res)
                        except Exception as e:
                            failed += 1
                            self.signals.error.emit(idx, str(e))
                        completed += 1
                        self.signals.progress.emit(completed, total)
            except Exception as e:
                self.signals.log.emit(f"Batch error: {e}")
            finally:
                cancelled = self._cancel.is_set() and bool(pending)
                pool.shutdown(wait=not cancelled, cancel_futures=True)

        if cancelled:
            self.signals.log.emit(
                f"Batch cancelled: {completed}/{total} jobs finished, {len(pending)} dropped."
            )
        elif failed:
            self.signals.log.emit(f"Batch finished with errors: {failed}/{total} jobs failed.")
        else:
            self.signals.log.emit("Batch processing complete.")
        self.signals.batch_finished.emit(results)
