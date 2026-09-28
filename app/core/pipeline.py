"""Pipeline — manages the overall analysis workflow state."""

from PySide6.QtCore import QObject, Signal


class Pipeline(QObject):
    """Tracks the state of a single IHM analysis run."""

    step_completed = Signal(str)
    error_occurred = Signal(str, str)  # step_name, message

    STEPS = [
        "load_input",
        "load_spectra",
        "select_regions",
        "calibrate",
        "generate_params",
        "fit",
        "results",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: dict = {}
        self._current_step = 0

    @property
    def current_step(self) -> str:
        if self._current_step < len(self.STEPS):
            return self.STEPS[self._current_step]
        return "done"

    def set_data(self, key: str, value):
        self._state[key] = value

    def get_data(self, key: str, default=None):
        return self._state.get(key, default)

    def advance(self):
        if self._current_step < len(self.STEPS):
            name = self.STEPS[self._current_step]
            self._current_step += 1
            self.step_completed.emit(name)

    def reset(self):
        self._state.clear()
        self._current_step = 0

    def get_state(self) -> dict:
        return dict(self._state)
