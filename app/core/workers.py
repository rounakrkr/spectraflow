"""QThread workers for background tasks (fit, spectrum loading)."""

from PySide6.QtCore import QThread, Signal, QObject


class WorkerSignals(QObject):
    """Shared signals for all workers."""
    progress = Signal(int, float)    # iteration, target_value
    finished = Signal(object)        # result object
    error = Signal(str)              # error message
    log = Signal(str)                # log message


class FitWorker(QThread):
    """Runs the lmfit minimization in a background thread."""

    def __init__(self, fit_fn=None, fit_args=None, parent=None):
        super().__init__(parent)
        self.signals = WorkerSignals()
        self._fit_fn = fit_fn
        self._fit_args = fit_args or ()
        self._running = True

    def run(self):
        try:
            if self._fit_fn is not None:
                result = self._fit_fn(*self._fit_args)
                self.signals.finished.emit(result)
            else:
                self.signals.error.emit("No fit function provided.")
        except Exception as e:
            self.signals.error.emit(str(e))

    def stop(self):
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running


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
