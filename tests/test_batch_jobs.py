import csv
import os

from app.core import batch_jobs, exporter


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()


def test_discover_mixtures_natural_order_and_filters(tmp_path):
    for d in ("mix10", "mix2", "mix1", ".hidden", "mix1-DATA", "mix1-FIGURES", "results"):
        (tmp_path / d).mkdir()
    _touch(str(tmp_path / "sample.jdf"))
    _touch(str(tmp_path / "notes.txt"))

    found = batch_jobs.discover_mixtures(str(tmp_path), exclude=(str(tmp_path / "results"),))

    assert [os.path.basename(p) for p in found] == ["mix1", "mix2", "mix10", "sample.jdf"]


def test_template_jobs_get_unique_out_roots(tmp_path):
    mixtures = [str(tmp_path / "a" / "1"), str(tmp_path / "b" / "1"), str(tmp_path / "c")]
    jobs = batch_jobs.build_template_jobs("t.inp", mixtures, str(tmp_path / "out"))

    roots = [j.out_root for j in jobs]
    assert len(set(r.lower() for r in roots)) == 3
    assert all(j.inp_path == os.path.abspath("t.inp") for j in jobs)
    assert [j.mix_path for j in jobs] == [os.path.abspath(m) for m in mixtures]


def test_input_file_jobs_keep_their_own_mixture(tmp_path):
    jobs = batch_jobs.build_input_file_jobs(["x/run.inp", "y/run.inp"], str(tmp_path))

    assert all(j.mix_path is None for j in jobs)
    assert jobs[0].out_root != jobs[1].out_root


def test_worker_environ_restores_previous_values(monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "8")
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)

    with batch_jobs.worker_environ():
        assert os.environ["OMP_NUM_THREADS"] == "1"
        assert os.environ["MKL_NUM_THREADS"] == "1"

    assert os.environ["OMP_NUM_THREADS"] == "8"
    assert "MKL_NUM_THREADS" not in os.environ


def test_batch_summary_has_one_column_per_component(tmp_path):
    rows = [
        {"label": "m1", "status": "done", "component_names": ["A", "B"],
         "concentrations": [0.25, 0.75], "nfev": 120, "elapsed": 3.5, "message": "ok"},
        {"label": "m2", "status": "failed", "message": "boom"},
        {"label": "m3", "status": "done", "component_names": ["A", "B"],
         "concentrations": [0.5, 0.5], "nfev": 80, "elapsed": 2.0, "message": "ok"},
    ]
    path = exporter.write_batch_summary(str(tmp_path / "summary.csv"), rows)

    with open(path, newline="", encoding="utf-8") as f:
        table = list(csv.reader(f))

    assert table[0] == ["Mixture", "Status", "A (%)", "B (%)", "nfev", "Elapsed_s", "Message"]
    assert table[1][:4] == ["m1", "done", "25.00000", "75.00000"]
    assert table[2] == ["m2", "failed", "", "", "", "", "boom"]
    assert len(table) == 4
