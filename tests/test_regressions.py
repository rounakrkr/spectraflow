"""Regression tests for the bugs found in the September 2026 audit."""

import time

import numpy as np
import pytest

from app.core.batch_processor import BatchProcessor
from app.core.workers import FitCancelled, FitWorker
from app.panels.peak_editor import pseudo_voigt
from app.panels.spectrum_panel import SpectrumLoadError, load_text_spectrum


def _double(path):          # module-level so it is picklable
    return path * 2


def _slow(path):
    time.sleep(0.4)
    return path


# ── calibration_done ───────────────────────────────────────────────
def test_calibration_signal_delivers_int_keyed_payload(qapp):
    from app.panels.calibration_panel import CalibrationPanel
    panel = CalibrationPanel()
    ppm = np.linspace(12, -1, 64)
    panel.add_component("A", ppm, np.random.rand(64))
    panel.add_component("B", ppm, np.random.rand(64))
    panel._drift_slider.value = 0.1
    got = []
    panel.calibration_done.connect(got.append)
    panel._save()
    assert got and got[0][0]["drift"] == pytest.approx(0.1)
    assert set(got[0]) == {0, 1}


# ── spectrum loading ───────────────────────────────────────────────
def test_loader_rejects_single_column(tmp_path):
    f = tmp_path / "one.txt"
    np.savetxt(f, np.random.rand(50))
    with pytest.raises(SpectrumLoadError, match="single column"):
        load_text_spectrum(str(f))


@pytest.mark.parametrize("delim", [" ", ",", ";", "\t"])
def test_loader_accepts_common_delimiters_and_header(tmp_path, delim):
    f = tmp_path / "two.txt"
    rows = [f"ppm{delim}intensity"] + [f"{x:.4f}{delim}{x*2:.4f}" for x in np.linspace(10, 0, 20)]
    f.write_text("\n".join(rows))
    ppm, data = load_text_spectrum(str(f))
    assert ppm[0] == pytest.approx(10.0) and data[0] == pytest.approx(20.0) and len(ppm) == 20


def test_loader_rejects_nan(tmp_path):
    f = tmp_path / "nan.txt"
    f.write_text("1.0 2.0\nnan 3.0\n4.0 5.0\n")
    with pytest.raises(SpectrumLoadError):
        load_text_spectrum(str(f))


# ── FitWorker cancellation ─────────────────────────────────────────
def test_fitworker_stop_aborts_via_iter_cb(qapp):
    seen = {"iters": 0, "aborted": False}

    def fit(iter_cb=None):
        for i in range(1000):
            seen["iters"] = i
            if iter_cb(None, i, np.ones(3)):
                seen["aborted"] = True
                return "partial"
        return "full"

    w = FitWorker(fit_fn=fit)
    events = []
    w.signals.cancelled.connect(lambda: events.append("cancelled"))
    w.signals.finished.connect(lambda r: events.append("finished"))
    progress = []
    w.signals.progress.connect(lambda i, t: progress.append((i, t)))
    w.stop()
    w.run()  # synchronous
    assert events == ["cancelled"] and seen["aborted"] and seen["iters"] == 0
    assert progress and progress[0][1] == pytest.approx(3.0)


def test_fitworker_completes_and_supports_fit_fn_without_callback(qapp):
    w = FitWorker(fit_fn=lambda a, b: a + b, fit_args=(1, 2))
    out = []
    w.signals.finished.connect(out.append)
    w.run()
    assert out == [3]


def test_fitworker_fitcancelled_exception(qapp):
    def fit():
        raise FitCancelled()
    w = FitWorker(fit_fn=fit)
    events = []
    w.signals.cancelled.connect(lambda: events.append("cancelled"))
    w.signals.error.connect(lambda m: events.append("error"))
    w.run()
    assert events == ["cancelled"]


# ── BatchProcessor ─────────────────────────────────────────────────
def test_batch_rejects_unpicklable_fit_fn_once(qapp):
    b = BatchProcessor()
    errors, logs, finished = [], [], []
    b.signals.error.connect(lambda i, m: errors.append((i, m)))
    b.signals.log.connect(logs.append)
    b.signals.batch_finished.connect(finished.append)
    b.configure(["a", "b", "c"], fit_fn=lambda p: p)
    b.run()
    assert len(errors) == 1 and errors[0][0] == -1 and "module-level" in errors[0][1]
    assert not any("complete" in m.lower() for m in logs)
    assert finished == [[None, None, None]]


def test_batch_runs_picklable_fn(qapp):
    b = BatchProcessor()
    finished, logs = [], []
    b.signals.batch_finished.connect(finished.append)
    b.signals.log.connect(logs.append)
    b.configure(["x", "y"], fit_fn=_double, n_workers=2)
    b.run()
    assert finished == [["xx", "yy"]] and logs[-1] == "Batch processing complete."


def test_batch_cancel_drops_queued_jobs(qapp):
    b = BatchProcessor()
    finished, logs = [], []
    b.signals.batch_finished.connect(finished.append)
    b.signals.log.connect(logs.append)
    b.configure([str(i) for i in range(8)], fit_fn=_slow, n_workers=1)
    b.cancel()          # after configure(), which clears the flag
    b.run()
    assert any("cancelled" in m.lower() for m in logs)
    assert sum(r is not None for r in finished[0]) < 8


# ── terminal goto ──────────────────────────────────────────────────
def test_goto_unknown_panel_reports_error(window):
    window._on_terminal_command("goto nope")
    text = window._terminal._output.toPlainText()
    assert "Unknown panel: nope" in text and "Navigated to nope" not in text


def test_goto_known_panel_navigates(window):
    window._on_terminal_command("goto FIT")
    assert window._stack.currentWidget() is window._panels["fit"]


# ── results table ──────────────────────────────────────────────────
def test_relative_column_ignores_zero_concentration(window):
    r = window._results
    ppm = np.linspace(12, -1, 128)
    e = np.random.rand(128)
    r.set_results(ppm, e, e * 0.9, [e, e, e], [0.0, 0.2, 0.4])
    rel = [r._table.item(i, 2).text() for i in range(3)]
    assert rel == ["0.0000", "1.0000", "2.0000"]


def test_relative_column_all_zero_shows_dash(window):
    r = window._results
    ppm = np.linspace(12, -1, 64)
    e = np.random.rand(64)
    r.set_results(ppm, e, e, [e], [0.0])
    assert r._table.item(0, 2).text() == "—"


# ── SpectrumViewer.plot ────────────────────────────────────────────
def test_plot_updates_pen_on_existing_trace(qapp):
    from app.widgets.spectrum_viewer import SpectrumViewer
    v = SpectrumViewer()
    x = np.arange(10.0)
    item = v.plot(x, x, name="t", color="#ff0000", width=1.0)
    v.plot(x, x, name="t", color="#00ff00", width=3.0)
    pen = item.opts["pen"]
    assert pen.color().name() == "#00ff00" and pen.widthF() == pytest.approx(3.0)


# ── Peak preview lineshape ─────────────────────────────────────────
def test_pseudo_voigt_fwhm_uses_spectrometer_frequency():
    ppm = np.linspace(6, 8, 200001)
    for sfo in (400.0, 800.0):
        y = pseudo_voigt(ppm, 7.0, fwhm_hz=8.0, sfo_mhz=sfo, beta=0.0)
        above = ppm[y >= 0.5]
        assert (above[-1] - above[0]) == pytest.approx(8.0 / sfo, rel=1e-3)


def test_pseudo_voigt_gaussian_fraction_and_phase():
    ppm = np.linspace(6, 8, 20001)
    lor = pseudo_voigt(ppm, 7.0, 8.0, 400.0, beta=0.0)
    gau = pseudo_voigt(ppm, 7.0, 8.0, 400.0, beta=1.0)
    assert not np.allclose(lor, gau)
    far = np.argmin(np.abs(ppm - 7.1))
    assert gau[far] < lor[far]                    # Gaussian tails fall faster
    ph = pseudo_voigt(ppm, 7.0, 8.0, 400.0, beta=0.0, phi_deg=90.0)
    assert abs(ph[np.argmin(np.abs(ppm - 7.0))]) < 1e-6   # pure dispersion is 0 at centre
    assert ph.min() < 0 < ph.max()


def test_peak_editor_updates_in_place_and_removes_extras(window):
    p = window._peaks
    ppm = np.linspace(12, -1, 256)
    p.set_experimental(ppm, np.random.rand(256))
    p.set_peaks([{"u": 7.2, "fwhm": 5, "k": .5, "b": .5, "phi": 0, "group": 0},
                 {"u": 3.3, "fwhm": 8, "k": .3, "b": .2, "phi": 10, "group": 1}])
    assert {"Peak_1", "Peak_2", "Total Fit"} <= set(p._viewer._plots)
    p._peak_spin.setValue(2); p._remove_peak()
    assert "Peak_2" not in p._viewer._plots and "Peak_1" in p._viewer._plots


# ── Region selector ────────────────────────────────────────────────
def test_add_region_disabled_until_spectrum_loaded(window):
    r = window._regions
    assert not r._add_btn.isEnabled()
    r.set_spectrum(np.linspace(12, -1, 128), np.random.rand(128))
    assert r._add_btn.isEnabled()
    r._add_region()
    assert len(r._regions) == 1


def test_region_colour_follows_theme(window):
    from app.theme.theme_manager import COLORS
    r = window._regions
    r.set_spectrum(np.linspace(12, -1, 128), np.random.rand(128))
    r._add_region()
    window._toggle_theme()      # dark -> light
    assert r._regions[0].brush.color().name().lower() == COLORS["light"]["plot_region"][:7].lower()


# ── Glass backdrop ─────────────────────────────────────────────────
def test_gradient_background_glass_toggles_opacity(qapp):
    from PySide6.QtCore import Qt
    from app.widgets.gradient_background import GradientBackground
    g = GradientBackground()
    assert g.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    g.set_glass(True)
    assert not g.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    g.set_glass(False)
    assert g.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
