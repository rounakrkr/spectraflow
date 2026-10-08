"""Real fits through run_ihm and the batch process pool, no mocking of the fit.

Only ``load_mixture`` is replaced (simulated spectra instead of Bruker data);
the template ``.inp`` is parsed by pyihm and every component/fit step is real.
Workers are forked, so they inherit the replacement.
"""
import glob
import multiprocessing
import os
import pickle

import numpy as np
import pytest

kz = pytest.importorskip("klassez")
pytest.importorskip("pyihm")

from app.core import batch_jobs, ihm_runner as ihm  # noqa: E402
from app.core.batch_processor import BatchProcessor  # noqa: E402
from test_e2e_fit import COMPONENTS, _sim_dict  # noqa: E402

FRACTIONS = {
    "mixA": np.array([0.5, 0.3, 0.2]),
    "mixB": np.array([0.2, 0.2, 0.6]),
}


def _simulate(fractions):
    shifts, amps = [], []
    for c, x in zip(COMPONENTS.values(), fractions):
        a = np.array(c["amps"], float)
        shifts += list(c["shifts"])
        amps += list(a / a.sum() * c["H"] * x * 100)
    M = kz.Spectrum_1D(_sim_dict(shifts, amps), isexp=False)
    M.process()
    return M


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spectra = {name: _simulate(f) for name, f in FRACTIONS.items()}
    M0 = spectra["mixA"]

    comp_lines = []
    for name, c in COMPONENTS.items():
        peaks = {
            i: kz.fit.Peak(dict(M0.acqus), u=u + 0.004, fwhm=1.5, k=a, b=0.0, phi=0.0,
                           N=M0.r.shape[-1])
            for i, (u, a) in enumerate(zip(c["shifts"], c["amps"]), start=1)
        }
        path = tmp_path / f"comp_{name}.fvf"
        kz.fit.write_vf(str(path), peaks, (float(M0.ppm.max()), float(M0.ppm.min())), 1, header=True)
        comp_lines.append(f"{path}, {c['H']}H")

    mix_dirs = {}
    for name in spectra:
        d = tmp_path / "mixtures" / name
        d.mkdir(parents=True)
        mix_dirs[name] = str(d)

    template = tmp_path / "template.inp"
    sep = os.linesep
    template.write_text(sep.join([
        "BASE_FILENAME", str(tmp_path / "template-out"), "",
        "MIX_PATH", mix_dirs["mixA"], "",
        "COMP_PATH", *comp_lines, "",
        "FIT_LIMITS", "(7.5, 0.5)", "",
        "FIT_BDS", "utol = 0.2", "utol_sg = 0.1", "stol = 10", "ktol = 0.01", "",
        "PLT_OPTS", "ext=png, dpi=80", "",
    ]))

    def fake_load_mixture(path, mix_kws=None, proc_opt=None, mix_txtf=None):
        return spectra[os.path.basename(path)]

    monkeypatch.setattr(ihm, "load_mixture", fake_load_mixture)
    return tmp_path, str(template), mix_dirs


def test_run_ihm_applies_template_to_another_mixture(workspace):
    tmp, template, mix_dirs = workspace
    out_root = str(tmp / "out" / "mixB")

    summary = ihm.run_ihm(template, method="tight", align=True, out_root=out_root,
                          overrides={"mix_path": mix_dirs["mixB"]})

    assert summary["component_names"] == ["comp_A", "comp_B", "comp_C"]
    np.testing.assert_allclose(summary["concentrations"], FRACTIONS["mixB"], atol=0.02)
    assert summary["mixture_path"] == os.path.abspath(mix_dirs["mixB"])
    assert os.path.isfile(summary["outputs"]["csv"])
    assert os.path.isfile(summary["outputs"]["report"])
    assert pickle.loads(pickle.dumps(summary)) == summary
    assert not glob.glob(str(tmp / "*-cal.fvf"))


def test_run_ihm_rejects_unknown_override(workspace):
    _, template, _ = workspace
    with pytest.raises(ValueError, match="Unknown override"):
        ihm.run_ihm(template, overrides={"mixture": "x"})


@pytest.mark.skipif(multiprocessing.get_start_method() != "fork",
                    reason="the simulated load_mixture reaches workers only through fork")
def test_batch_pool_isolates_failures_and_keeps_order(workspace, qapp):
    tmp, template, mix_dirs = workspace
    ghost = str(tmp / "mixtures" / "missing")
    mixtures = [mix_dirs["mixA"], ghost, mix_dirs["mixB"]]
    jobs = batch_jobs.build_template_jobs(template, mixtures, str(tmp / "batch-out"))

    results, errors = [], []
    b = BatchProcessor()
    b.signals.batch_finished.connect(results.append)
    b.signals.error.connect(lambda i, m: errors.append((i, m)))
    b.configure(jobs, fit_fn=batch_jobs.batch_fit_fn("tight", True), n_workers=2)
    b.run()

    (finished,) = results
    assert finished[1] is None
    assert [i for i, _ in errors] == [1] and "FileNotFoundError" in errors[0][1]
    np.testing.assert_allclose(finished[0]["concentrations"], FRACTIONS["mixA"], atol=0.02)
    np.testing.assert_allclose(finished[2]["concentrations"], FRACTIONS["mixB"], atol=0.02)
    assert finished[0]["label"] == "mixA" and finished[2]["label"] == "mixB"
    assert finished[0]["out_root"] != finished[2]["out_root"]
    assert not glob.glob(str(tmp / "*-cal.fvf"))
