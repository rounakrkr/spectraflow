"""Regression tests for the UI polish round: stepper arrows, QSS icons, axis
labels, component stacking, cancel-is-not-an-error, and peak-editor wiring."""

import re
import time
from pathlib import Path

import lmfit as lm
import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QAbstractSpinBox

from app.core import engine as eng
from app.core.workers import FitCancelled
from app.theme.theme_manager import ThemeManager
from app.widgets.parameter_slider import ParameterSlider
from app.widgets.spectrum_viewer import SpectrumViewer


def _pump(app, ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait(app, cond, timeout=5.0):
    t = time.time()
    while not cond() and time.time() - t < timeout:
        _pump(app, 10)
    return cond()


# ── QSS / icons ────────────────────────────────────────────────────
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_qss_arrows_are_svg_files_not_border_triangles(theme):
    qss = (ThemeManager.THEME_DIR / f"{theme}.qss").read_text(encoding="utf-8")
    assert not re.search(r"border-top:\s*\d+px solid #[0-9a-fA-F]{3,6};\s*\n\s*margin-right", qss)
    urls = re.findall(r'url\("@ICONS@/([^"]+)"\)', qss)
    assert urls, "arrow rules must use image: url(...)"
    for name in urls:
        assert (ThemeManager.ICON_DIR / name).is_file(), name


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_spinbox_buttons_visible_in_both_themes(qapp, theme):
    qss = (ThemeManager.THEME_DIR / f"{theme}.qss").read_text(encoding="utf-8")
    block = re.search(r"QSpinBox::up-button, QDoubleSpinBox::up-button \{(.*?)\}", qss, re.S).group(1)
    assert "width: 0" not in block and "width: 20px" in block


# ── ParameterSlider ────────────────────────────────────────────────
def test_slider_spinbox_steps_and_syncs(qapp):
    s = ParameterSlider("δ drift", -0.5, 0.5, 0.0, 0.001, "ppm", 4)
    seen = []
    s.value_changed.connect(seen.append)
    assert s.spinbox.buttonSymbols() != QAbstractSpinBox.ButtonSymbols.NoButtons
    s.spinbox.stepBy(1)
    assert s.value == pytest.approx(0.001)
    assert s._slider.value() == 10                      # slider follows the stepper
    s.spinbox.stepBy(-3)
    assert s.value == pytest.approx(-0.002)
    assert seen[-1] == pytest.approx(-0.002)


def test_slider_text_not_clipped_and_columns_align(window, qapp):
    window._navigate("peaks")
    window.show()
    _pump(qapp, 100)
    pe = window._peaks
    sliders = pe._sliders
    assert len({s._label.width() for s in sliders}) == 1
    assert len({s.spinbox.width() for s in sliders}) == 1
    for s in sliders:
        spin = s.spinbox
        widest = max((spin.textFromValue(spin.minimum()), spin.textFromValue(spin.maximum())), key=len)
        assert spin.lineEdit().width() >= spin.fontMetrics().horizontalAdvance(widest)
        assert s._label.width() >= s._label.fontMetrics().horizontalAdvance(s._label.text())


# ── Axis labels ────────────────────────────────────────────────────
def test_viewer_axes_have_no_si_prefix(qapp):
    v = SpectrumViewer()
    for name in ("left", "bottom"):
        assert v.plot_widget.getAxis(name).autoSIPrefix is False
    assert "Ma.u." not in v.plot_widget.getAxis("left").labelString()


# ── Component stacking ─────────────────────────────────────────────
def test_components_loaded_twice_replace_not_stack(window):
    n = 2000
    ppm = np.linspace(10, 0, n)
    window._engine._state["ppm"] = ppm
    window._engine._state["I"] = 1.0
    comps = [np.random.rand(n) for _ in range(3)]
    names = ["bzac", "dmso", "EC"]
    for _ in range(3):
        window._on_components_loaded(comps, names)
    assert window._calibration._comp_combo.count() == 3
    assert len(window._calibration._components) == 3
    assert sorted(window._spectrum._spectra) == sorted(names)


def test_new_mixture_clears_previous_analysis_views(window):
    n = 500
    ppm = np.linspace(10, 0, n)
    window._engine._state["ppm"] = ppm
    window._engine._state["I"] = 1.0
    window._on_mixture_loaded(ppm, np.random.rand(n))
    window._on_components_loaded([np.random.rand(n)], ["a"])
    window._on_mixture_loaded(ppm, np.random.rand(n))
    assert window._calibration._comp_combo.count() == 0
    assert list(window._spectrum._spectra) == ["Mixture"]


# ── Cancel is not an error ─────────────────────────────────────────
def test_worker_fitcancelled_emits_cancelled_not_failed(qapp):
    def fn():
        raise FitCancelled("Fit cancelled by user")

    w = eng._Worker(fn)
    got = {"cancelled": 0, "failed": []}
    w.cancelled.connect(lambda: got.__setitem__("cancelled", got["cancelled"] + 1))
    w.failed.connect(got["failed"].append)
    w.start()
    assert _wait(qapp, lambda: got["cancelled"] == 1)
    w.wait()
    assert got["failed"] == []


def test_worker_other_exceptions_still_fail(qapp):
    def fn():
        raise ValueError("boom")

    w = eng._Worker(fn)
    failed = []
    w.failed.connect(failed.append)
    w.start()
    assert _wait(qapp, lambda: bool(failed))
    w.wait()
    assert "ValueError: boom" in failed[0]


def test_stop_button_requests_cancel_and_complete_does_not_log_stopped(window):
    fr = window._fit_runner
    got = []
    fr.stop_requested.connect(lambda: got.append(1))
    fr._on_start()
    fr._on_stop()
    assert got == [1] and "Stopped" in fr._status_label.text()
    fr._on_start()
    fr._log.clear()
    fr.on_fit_complete({})
    assert "stopped" not in fr._log.toPlainText().lower()
    assert "Complete" in fr._status_label.text()


def test_engine_error_dialog_not_shown_for_cancel(window, monkeypatch):
    shown = []
    monkeypatch.setattr("app.main_window.QMessageBox.warning", lambda *a, **k: shown.append(a))
    window._engine.fit_cancelled.emit()
    assert shown == []


# ── Peak editor wiring ─────────────────────────────────────────────
def _params():
    p = lm.Parameters()
    # singlet peak 1 of component 1 (group 0)
    p.add("S1_u1", value=7.0, min=6.9, max=7.1)
    p.add("S1_s1", value=2.0, min=0.0, max=7.0)
    p.add("S1_k1", value=0.5, min=0.0, max=0.51)
    p.add("S1_b1", value=0.5, min=0.0, max=1.0)
    # multiplet line 2 (group 3): u = U3 + o2
    p.add("S1_U3", value=4.5, min=4.4, max=4.6)
    p.add("S1_o2", value=0.01, min=0.0, max=0.02)
    p.add("S1_u2", expr="S1_U3 + S1_o2")
    p.add("S1_s2", value=1.0, min=0.0, max=6.0)
    p.add("S1_k2", value=0.3, min=0.0, max=0.31)
    p.add("S1_b2", value=0.2, min=0.0, max=1.0)
    return p


def test_apply_peak_edits_singlet_and_multiplet(qapp):
    e = eng.AnalysisEngine()
    e._state["param"] = _params()
    e._state["lims"] = [(7.2, 6.8), (4.7, 4.3)]
    errors = []
    e.error.connect(lambda s, m: errors.append(m))
    peaks = [
        {"key": "S1_", "idx": 1, "u": 7.05, "fwhm": 9.0, "k": 0.7, "b": 1.4, "phi": 0.0, "group": 0, "group0": 0},
        {"key": "S1_", "idx": 2, "u": 4.53, "fwhm": 1.5, "k": 0.3, "b": 0.2, "phi": 20.0, "group": 3, "group0": 3},
        {"u": 5.0, "fwhm": 5.0, "k": 0.5, "b": 0.5, "phi": 0.0, "group": 0},          # added in the editor
    ]
    res = e.apply_peak_edits(peaks)
    par = e._state["param"]
    assert res == {"applied": 2, "added_ignored": 1, "phase_ignored": 1}
    assert par["S1_u1"].value == pytest.approx(7.05)
    assert par["S1_u1"].min <= 7.05 <= par["S1_u1"].max
    assert par["S1_s1"].value == pytest.approx(9.0) and par["S1_s1"].max >= 9.0   # bound widened
    assert par["S1_k1"].value == pytest.approx(0.7)
    assert par["S1_b1"].value == pytest.approx(1.0)                                # clipped to [0, 1]
    assert par["S1_u2"].value == pytest.approx(4.53)                               # via offset
    assert par["S1_o2"].value == pytest.approx(0.03)
    assert errors == []


def test_apply_peak_edits_without_params_reports_error(qapp):
    e = eng.AnalysisEngine()
    errors = []
    e.error.connect(lambda s, m: errors.append((s, m)))
    assert e.apply_peak_edits([])["applied"] == 0
    assert errors and errors[0][0] == "apply_peak_edits"


def test_peak_editor_receives_peaks_and_shows_label(window):
    window._engine._state["ppm"] = np.linspace(10, 0, 1000)
    peaks = [
        {"u": 7.9, "fwhm": 1.1, "k": 9.0, "b": 0.5, "phi": 0.0, "group": 0, "label": "bzac · peak 1", "key": "S1_", "idx": 1},
        {"u": 7.5, "fwhm": 1.4, "k": 0.3, "b": 0.5, "phi": 0.0, "group": 0, "label": "bzac · peak 2", "key": "S1_", "idx": 2},
    ]
    window._on_peaks_ready(peaks)
    pe = window._peaks
    assert pe._peak_count.text() == "/ 2" and pe._peak_spin.maximum() == 2
    assert pe._peak_info.text() == "bzac · peak 1"
    assert pe._sl_k.value == pytest.approx(9.0)          # range widened beyond the 0..2 default
    pe._peak_spin.setValue(2)
    assert pe._peak_info.text() == "bzac · peak 2"
    pe.clear()
    assert pe._peak_count.text() == "/ 0"
