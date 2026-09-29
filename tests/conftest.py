import os
import sys
from pathlib import Path

# Headless Qt: must be set before any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp):
    from app.main_window import MainWindow
    w = MainWindow()
    w.apply_initial_theme(qapp, "dark")
    yield w
    w.close()
