"""End-to-end fit: a *real* pyihm fit through AnalysisEngine, no mocking.

Every other fit test monkeypatches ``calc_spectra`` / ``pre_alignment``; this one
simulates a noiseless 3-component mixture with known mole fractions, builds the
component .fvf files (deliberately mis-shifted by 0.004 ppm so the alignment
step has work to do) and checks that the engine recovers the concentrations.

Not covered: Bruker loading / .inp parsing (the simulated mixture is injected
into the engine state), multiplets, noise, baseline.
"""
from copy import deepcopy

import numpy as np
import pytest

kz = pytest.importorskip("klassez")
pytest.importorskip("pyihm")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from app.core.engine import AnalysisEngine  # noqa: E402

COMPONENTS = {                       # singlets: ppm positions and relative amplitudes
    "A": dict(shifts=(1.0, 1.5), amps=(3.0, 2.0), H=5),
    "B": dict(shifts=(3.2,), amps=(3.0,), H=3),
    "C": dict(shifts=(5.0, 6.5), amps=(1.0, 2.0), H=3),
}
TRUE_FRACTIONS = np.array([0.5, 0.3, 0.2])
BASE = dict(B0=14.1, nuc="1H", SWp=10, o1p=4.0, TD=16384)


def _sim_dict(shifts, amps):
    """Input dict for kz.Spectrum_1D(isexp=False), with the keys load_sim_1D derives."""
    n = len(shifts)
    d = deepcopy(BASE)
    d.update(shifts=tuple(shifts), amplitudes=tuple(amps), fwhm=(1.5,) * n,
             b=(0.0,) * n, phases=(0.0,) * n, mult=("s",) * n, Jconst=(0,) * n)
    d["B0"] = abs(d["B0"]) * np.sign(kz.sim.gamma[d["nuc"]])
    d["SFO1"] = d["B0"] * kz.sim.gamma[d["nuc"]]
    d["SW"] = d["SWp"] * abs(d["SFO1"])
    d["dw"] = 1 / d["SW"]
    d["t1"] = np.linspace(0, d["TD"] * d["dw"], d["TD"])
    d["AQ"] = d["t1"][-1]
    d["o1"] = d["o1p"] * d["SFO1"]
    return d


def _wait_for(engine, signal, trigger, timeout_ms=120_000):
    """Run ``trigger()`` and spin a Qt loop until ``signal`` (or an engine error) fires."""
    loop, got, errors = QEventLoop(), [], []
    signal.connect(lambda *a: (got.append(a), loop.quit()))
    engine.error.connect(lambda step, msg: (errors.append((step, msg)), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    trigger()
    loop.exec()
    assert not errors, errors
    assert got, "timed out waiting for the engine"
    return got[0]


@pytest.fixture
def engine_with_mixture(qapp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # klassez writes a .procs file next to simulated data

    mix_shifts, mix_amps = [], []
    for c, x in zip(COMPONENTS.values(), TRUE_FRACTIONS):
        a = np.array(c["amps"], float)
        mix_shifts += list(c["shifts"])
        mix_amps += list(a / a.sum() * c["H"] * x * 100)
    M = kz.Spectrum_1D(_sim_dict(mix_shifts, mix_amps), isexp=False)
    M.process()

    paths = []
    for name, c in COMPONENTS.items():
        peaks = {
            i: kz.fit.Peak(dict(M.acqus), u=u + 0.004, fwhm=1.5, k=a, b=0.0, phi=0.0,
                           N=M.r.shape[-1])
            for i, (u, a) in enumerate(zip(c["shifts"], c["amps"]), start=1)
        }
        path = str(tmp_path / f"comp_{name}.fvf")
        kz.fit.write_vf(path, peaks, (float(M.ppm.max()), float(M.ppm.min())), 1, header=True)
        paths.append(path)

    eng = AnalysisEngine()
    Hs = [c["H"] for c in COMPONENTS.values()]
    eng._state.update(M=M, ppm=M.ppm, exp=np.copy(M.r), acqus=dict(M.acqus),
                      mix_path="synthetic", Hs=list(Hs))
    _wait_for(eng, eng.components_loaded, lambda: eng.load_components(paths, Hs=Hs))
    eng.set_regions([(7.5, 0.5)])
    eng.set_boundaries({})
    _wait_for(eng, eng.params_ready, eng.generate_params)
    return eng


def test_real_tight_fit_recovers_known_concentrations(engine_with_mixture):
    eng = engine_with_mixture
    names = list(eng._state["param"])
    assert [n for n in names if n.endswith("_I")] == ["S1_I", "S2_I", "S3_I"]

    (res,) = _wait_for(eng, eng.fit_finished, lambda: eng.run_fit(method="tight", align=True),
                       timeout_ms=300_000)
    assert res["component_names"] == ["comp_A", "comp_B", "comp_C"]
    assert res["component_idx"] == [1, 2, 3]
    np.testing.assert_allclose(res["concentrations"], TRUE_FRACTIONS, atol=0.01)
    assert res["convergence"], "no convergence history recorded"
