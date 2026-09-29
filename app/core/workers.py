"""QThread workers for background tasks (fit, spectrum loading)."""

import inspect
import threading

import numpy as np
from PySide6.QtCore import QThread, Signal, QObject


class WorkerSignals(QObject):
    """Shared signals for all workers."""
    progress = Signal(int, float)    # iteration, target_value
    finished = Signal(object)        # result object
    cancelled = Signal()             # stop() honoured before completion
    error = Signal(str)              # error message
    log = Signal(str)                # log message


class FitCancelled(Exception):
    """Raise from a fit function to abort cooperatively."""


class FitWorker(QThread):
    """Runs the lmfit minimization in a background thread.

    Cancellation is cooperative. If ``fit_fn`` accepts an ``iter_cb`` keyword
    (or ``**kwargs``) it receives :meth:`iter_cb`, which has lmfit's iteration
    callback signature ``(params, iter, resid, *args, **kws)``. It emits
    ``progress`` and returns ``True`` once :meth:`stop` was called, which
    makes lmfit abort the minimisation. Fit functions that do not take a
    callback can poll :attr:`should_stop` instead.
    """

    def __init__(self, fit_fn=None, fit_args=None, parent=None):
        super().__init__(parent)
        self.signals = WorkerSignals()
        self._fit_fn = fit_fn
        self._fit_args = fit_args or ()
        self._stop = threading.Event()

    # ── cancellation ────────────────────────────────────────
    def stop(self):
        """Request cancellation; takes effect at the next callback/poll."""
        self._stop.set()

    @property
    def should_stop(self) -> bool:
        return self._stop.is_set()

    @property
    def is_running(self) -> bool:
        return self.isRunning() and not self._stop.is_set()

    # ── lmfit hook ──────────────────────────────────────────
    def iter_cb(self, params, iteration, resid, *args, **kws):
        """lmfit ``iter_cb``: report progress, return True to abort."""
        try:
            target = float(np.sum(np.square(np.asarray(resid))))
        except (TypeError, ValueError):
            target = float("nan")
        self.signals.progress.emit(int(iteration), target)
        return self._stop.is_set()

    def _accepts_iter_cb(self) -> bool:
        try:
            params = inspect.signature(self._fit_fn).parameters
        except (TypeError, ValueError):
            return False
        return "iter_cb" in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )

    def run(self):
        if self._fit_fn is None:
            self.signals.error.emit("No fit function provided.")
            return
        try:
            kwargs = {"iter_cb": self.iter_cb} if self._accepts_iter_cb() else {}
            result = self._fit_fn(*self._fit_args, **kwargs)
        except FitCancelled:
            self.signals.cancelled.emit()
            return
        except Exception as e:
            self.signals.error.emit(str(e))
            return
        if self._stop.is_set():
            self.signals.cancelled.emit()   # lmfit returns a partial result on abort
        else:
            self.signals.finished.emit(result)


class SpectrumLoadWorker(QThread):
    """Loads spectrum files in the background."""

    def __init__(self, load_fn=None, path: str = "", parent=None):
        super().__init__(parent)
        self.signals = WorkerSignals()
        self._load_fn = load_fn
        self._path = path

    def run(self):
        try:
            if self._load_fn is not None:
                result = self._load_fn(self._path)
                self.signals.finished.emit(result)
            else:
                self.signals.error.emit("No load function provided.")
        except Exception as e:
            self.signals.error.emit(str(e))
