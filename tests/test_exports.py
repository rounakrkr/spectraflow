"""Tests for result exports, -cal.fvf saving, pre-alignment toggle and auto-save."""

import os
from types import SimpleNamespace

import klassez as kz
import lmfit
import numpy as np
import pytest

from app.core import exporter

N = 2048


@pytest.fixture
def acqus():
    return {"t1": np.arange(N) / 4000.0, "SFO1": 400.0, "o1p": 5.0, "SW": 4000.0, "nuc": "1H"}


@pytest.fixture
def results(acqus):
    ppm = np.linspace(10, 0, N)
    peaks = [
        [kz.fit.Peak(acqus, u=7.5, fwhm=2, k=2.0, N=N), kz.fit.Peak(acqus, u=3.0, fwhm=2, k=1.0, N=N)],
        [kz.fit.Peak(acqus, u=5.0, fwhm=2, k=3.0, N=N)],
    ]
    comps = [np.sum([p() for p in ps], axis=0).real for ps in peaks]
    exp = np.sum(comps, axis=0)
    return {
        "ppm": ppm, "experimental": exp, "total_fit": exp, "components": comps,
        "concentrations": [0.4, 0.6], "component_names": ["A", "B"], "I": 1.5,
        "peaks": peaks, "component_idx": [1, 2], "lims": [(8.0, 2.0)],
        "plims": [slice(100, 1900)], "mixture_path": "/data/mix", "x_label": None,
        "convergence": [(1, 1e-3), (2, 5e-4), (3, 1e-4)], "Hs": [3.0, 3.0],
    }


# ── exporter ───────────────────────────────────────────────────────
def test_write_csv_layout(tmp_path, results):
    path = exporter.write_csv(str(tmp_path / "r.csv"), results)
    with open(path) as f:
        header = f.readline().split()
    assert header == ["PPM_SCALE", "EXPERIMENTAL", "TOTAL", "COMPONENT_1", "COMPONENT_2"]
    data = np.loadtxt(path, skiprows=1)
    assert data.shape == (N, 5)
    assert np.allclose(data[:, 2], data[:, 3] + data[:, 4])


def test_concentrations_csv(tmp_path, results):
    path = exporter.write_concentrations_csv(str(tmp_path / "c.csv"), results)
    lines = open(path).read().splitlines()
    assert lines[0] == "Component,Concentration_percent,Relative"
    assert lines[1] == '"A",40.00000,1.00000'
    assert lines[2] == '"B",60.00000,1.50000'


def test_concentrations_csv_zero_component(tmp_path, results):
    results["concentrations"] = [0.0, 1.0]
    lines = open(exporter.write_concentrations_csv(str(tmp_path / "c.csv"), results)).read().splitlines()
    assert lines[1] == '"A",0.00000,0.00000'
    assert lines[2] == '"B",100.00000,1.00000'


def test_report_matches_pyihm_layout(tmp_path, results):
    path = exporter.write_report(str(tmp_path / "fit.out"), results)
    text = open(path).read()
    assert "Mixture spectrum: /data/mix" in text
    assert "Absolute intensity correction: I = 1.50000000e+00" in text
    assert "Component   1:   40.00000% | Rel:    1.00000" in text
    assert "Component   2:   60.00000% | Rel:    1.50000" in text
    assert "Component 1 fitted parameters:" in text and "Component 2 fitted parameters:" in text
    assert "8.000:2.000" in text


def test_report_requires_peaks(tmp_path, results):
    results["peaks"] = None
    with pytest.raises(exporter.ExportError):
        exporter.write_report(str(tmp_path / "fit.out"), results)


def test_exports_reject_missing_results(tmp_path):
    with pytest.raises(exporter.ExportError):
        exporter.write_csv(str(tmp_path / "x.csv"), None)


def test_save_all_creates_pyihm_layout(tmp_path, results):
    out = exporter.save_all(str(tmp_path / "run"), results, ext="png", dpi=60)
    assert os.path.isfile(tmp_path / "run.out")
    assert os.path.isfile(tmp_path / "run-DATA" / "run-result.csv")
    assert os.path.isfile(tmp_path / "run-DATA" / "run.cnvg")
    names = {os.path.basename(p) for p in out["figures"]}
    assert {"run_total.png", "run_wcomp.png", "run_cnvg.png"} <= names
    assert not any(p.endswith(".tmp") for p in os.listdir(tmp_path / "run-FIGURES"))


# ── engine: drift + -cal.fvf ───────────────────────────────────────
def _engine_with_components(acqus, tmp_path):
    from app.core.engine import AnalysisEngine
    e = AnalysisEngine()
    paths = [str(tmp_path / "a.fvf"), str(tmp_path / "b.fvf")]
    peaks = [
        {1: kz.fit.Peak(acqus, u=7.0, fwhm=2, k=1.0, N=N)},
        {1: kz.fit.Peak(acqus, u=4.0, fwhm=2, k=1.0, N=N)},
    ]
    e._state.update(comp_paths=paths, comp_peaks=peaks, ppm=np.linspace(10, 0, N),
                    components=[p[1]() for p in peaks], drifts=[0.0, 0.0])
    return e, paths, peaks


def test_apply_drift_is_idempotent(qapp, acqus, tmp_path):
    e, _, peaks = _engine_with_components(acqus, tmp_path)
    e.apply_drift(0, 0.05)
    e.apply_drift(0, 0.05)
    assert peaks[0][1].u == pytest.approx(7.05)
    e.apply_drift(0, 0.0)
    assert peaks[0][1].u == pytest.approx(7.0)
    assert peaks[1][1].u == pytest.approx(4.0)


def test_save_calibrated_components_roundtrip(qapp, acqus, tmp_path):
    e, paths, peaks = _engine_with_components(acqus, tmp_path)
    e.apply_drift(1, -0.1)
    written = e.save_calibrated_components()
    assert written == [str(tmp_path / "a-cal.fvf"), str(tmp_path / "b-cal.fvf")]
    regions = kz.fit.read_vf(written[1])
    peak = next(v for k, v in regions[0].items() if isinstance(v, dict))
    assert peak["u"] == pytest.approx(3.9)


def test_save_calibrated_components_does_not_stack_cal_suffix(qapp, acqus, tmp_path):
    e, paths, _ = _engine_with_components(acqus, tmp_path)
    e._state["comp_paths"] = [str(tmp_path / "a-cal.fvf"), str(tmp_path / "b-cal.fvf")]
    written = e.save_calibrated_components()
    assert written == [str(tmp_path / "a-cal.fvf"), str(tmp_path / "b-cal.fvf")]


def test_save_calibrated_components_needs_components(qapp):
    from app.core.engine import AnalysisEngine
    e = AnalysisEngine()
    errors = []
    e.error.connect(lambda step, msg: errors.append(step))
    assert e.save_calibrated_components() == []
    assert errors == ["save_calibration"]


# ── engine: run_fit align toggle + result payload ──────────────────
def _fit(monkeypatch, align):
    from PySide6.QtCore import QEventLoop, QTimer
    from app.core import engine as eng

    n = 500
    M = SimpleNamespace(acqus={"x": 1, "nuc": "1H"}, freq=400.0,
                        r=np.ones(n), ppm=np.linspace(10, 0, n))
    param = lmfit.Parameters()
    param.add("S1_I", value=1.0)
    calls = []

    monkeypatch.setattr(eng.pyihm_fit, "calc_spectra",
                        lambda p, ns, acqus, N: [np.full(n, p["S1_I"].value)])
    monkeypatch.setattr(eng.pyihm_fit, "calc_spectra_obj",
                        lambda p, ns, acqus, N: [[SimpleNamespace(k=1.0, u=5.0, fwhm=2.0, phi=0.0, b=0.0, group=0)]])
    monkeypatch.setattr(eng.pyihm_fit, "pre_alignment",
                        lambda exp, acqus, ns, N, plims, p, dbg=False: (calls.append(1), p)[1])

    e = eng.AnalysisEngine()
    e._state.update(M=M, param=param, lims=[(6.0, 4.0)], I=1.0, mix_path="/data/mix",
                    c_idx=[0], Hs=[1], clean_Hs=[1], comp_names=["A"])
    finished, errors = [], []
    loop = QEventLoop()
    e.error.connect(lambda step, msg: (errors.append(msg), loop.quit()))
    e.fit_finished.connect(lambda r: (finished.append(r), loop.quit()))
    QTimer.singleShot(15000, loop.quit)
    e.run_fit("fast", align=align)
    loop.exec()
    assert not errors, errors
    assert len(finished) == 1
    return e, finished[0], calls


def test_run_fit_skips_alignment_when_disabled(qapp, monkeypatch):
    _, res, calls = _fit(monkeypatch, align=False)
    assert calls == []
    assert res["concentrations"][0] == pytest.approx(1.0)


def test_run_fit_aligns_by_default(qapp, monkeypatch):
    _, _, calls = _fit(monkeypatch, align=True)
    assert calls == [1]


def test_run_fit_payload_supports_export(qapp, monkeypatch, tmp_path):
    e, res, _ = _fit(monkeypatch, align=True)
    assert e.last_results is not None
    assert e.last_results["component_idx"] == res["component_idx"]
    assert res["component_idx"] == [1]
    assert res["lims"] == [(6.0, 4.0)]
    assert res["mixture_path"] == "/data/mix"
    assert res["convergence"] and res["convergence"][0][0] == 1
    path = exporter.write_report(str(tmp_path / "f.out"), res)
    assert "Component   1:  100.00000%" in open(path).read()


# ── GUI wiring ─────────────────────────────────────────────────────
def test_autosave_writes_outputs_next_to_mixture(window, results, tmp_path):
    mix = tmp_path / "sample.fid"
    mix.mkdir()
    window._engine._state["mix_path"] = str(mix)
    window._fit_runner._autosave_chk.setChecked(True)
    window._autosave_results(results)
    assert os.path.isfile(tmp_path / "sample-fit.out")
    assert os.path.isfile(tmp_path / "sample-fit-DATA" / "sample-fit-result.csv")


def test_autosave_prefers_input_file_output_root(window, results, tmp_path):
    window._engine._state["out_root"] = str(tmp_path / "custom")
    window._engine._state["plt_opt"] = {"ext": "png", "dpi": 60}
    window._autosave_results(results)
    assert os.path.isfile(tmp_path / "custom.out")
    assert os.path.isfile(tmp_path / "custom-FIGURES" / "custom_total.png")


def test_autosave_can_be_disabled(window):
    window._fit_runner._autosave_chk.setChecked(False)
    assert window._fit_runner.autosave_enabled is False


def test_results_panel_fills_h_correction_and_exports(window, results, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    r = window._results
    r.set_results(results["ppm"], results["experimental"], results["total_fit"], results["components"],
                  results["concentrations"], results["component_names"], export_data=results)
    assert r._table.item(0, 3).text() == "3.000"

    seen = []
    r.exported.connect(seen.append)
    target = str(tmp_path / "out.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (target, ""))
    r._export_csv()
    assert os.path.isfile(target) and os.path.isfile(tmp_path / "out-concentrations.csv")

    rep = str(tmp_path / "rep.out")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (rep, ""))
    r._export_report()
    assert os.path.isfile(rep)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path / "figs"))
    r._export_figures()
    assert os.path.isfile(tmp_path / "figs" / "fit_total.png")
    assert len(seen) == 3


def test_export_without_results_shows_message_not_crash(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a))
    window._results._export_data = None
    window._results._export_csv()
    assert shown
