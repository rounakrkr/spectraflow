"""Regression tests: relative paths in a pyihm input file, and -cal.fvf duplicates."""

import os


from app.core.engine import read_input_file_resolved, resolve_input_path

INP = """BASE_FILENAME
mix

MIX_PATH
test_spectrum.fid, spect='varian'

PROC_OPTS
wf: em, lb=1
zf: 2**16
adjph

COMP_PATH
comp/bzac.fvf, 5H
comp/dmso.fvf, 6H
comp/EC.fvf, 4H

FIT_BDS
utol=0.1
utol_sg=0.01
stol=5
ktol=0.01

FIT_LIMITS
  8.032,   7.858
  2.553,   2.426
"""


def test_relative_paths_resolve_against_input_file_folder(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    # extension-less input file, as shipped with pyihm
    (proj / "pyihm_input").write_text(INP, newline="\n")
    elsewhere = tmp_path / "somewhere_else"       # app started from another folder
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    parsed = read_input_file_resolved(str(proj / "pyihm_input"))

    assert parsed["mix_path"] == str(proj / "test_spectrum.fid")
    assert parsed["comp_path"] == [str(proj / "comp" / n) for n in ("bzac.fvf", "dmso.fvf", "EC.fvf")]
    assert parsed["Hs"] == [5, 6, 4]
    assert all(os.path.isabs(p) for p in parsed["comp_path"])


def test_absolute_paths_are_kept(tmp_path):
    p = str(tmp_path / "x.fvf")
    assert resolve_input_path(p, "/some/other/base") == os.path.normpath(p)


def test_falls_back_to_cwd_when_only_cwd_has_the_file(tmp_path, monkeypatch):
    base = tmp_path / "base"
    base.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "data.fid").write_text("x")
    monkeypatch.chdir(cwd)
    assert resolve_input_path("data.fid", str(base)) == str(cwd / "data.fid")


def test_component_folder_skips_cal_copies(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from app.panels.input_config import InputConfigPanel

    for n in ("bzac.fvf", "bzac-cal.fvf", "dmso.fvf", "dmso-cal.fvf", "EC.fvf", "EC-cal.fvf",
              "only-cal-cal.fvf"):
        (tmp_path / n).write_text("x")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))

    panel = InputConfigPanel()
    panel._add_comp_folder()

    names = [os.path.basename(p) for p in panel._comp_paths]
    # one entry per component; a lone "-cal" file with no plain sibling is kept
    assert sorted(names) == sorted(["bzac.fvf", "dmso.fvf", "EC.fvf", "only-cal-cal.fvf"])


# ── tick / untick component files ──────────────────────────────────
def _panel_with(qapp, names):
    from app.panels.input_config import InputConfigPanel
    panel = InputConfigPanel()
    for n in names:
        panel._add_comp_path(f"/data/comp/{n}")
    return panel


def test_component_rows_are_ticked_by_default(qapp):
    from PySide6.QtCore import Qt
    panel = _panel_with(qapp, ["bzac.fvf", "dmso.fvf", "EC.fvf"])
    assert all(panel._comp_list.item(i).checkState() == Qt.CheckState.Checked
               for i in range(3))
    assert len(panel.get_config()["comp_paths"]) == 3
    assert panel._comp_summary.text().startswith("3 of 3 selected")


def test_unticked_component_is_left_out_of_config(qapp):
    from PySide6.QtCore import Qt
    panel = _panel_with(qapp, ["bzac.fvf", "dmso.fvf", "EC.fvf"])

    panel._comp_list.item(1).setCheckState(Qt.CheckState.Unchecked)   # untick dmso

    got = [os.path.basename(p) for p in panel.get_config()["comp_paths"]]
    assert got == ["bzac.fvf", "EC.fvf"]                  # order preserved
    assert panel._comp_summary.text().startswith("2 of 3 selected")
    assert len(panel._comp_paths) == 3                    # still listed, can be re-ticked

    panel._comp_list.item(1).setCheckState(Qt.CheckState.Checked)
    assert len(panel.get_config()["comp_paths"]) == 3


def test_save_config_emits_only_ticked_components(qapp):
    from PySide6.QtCore import Qt
    panel = _panel_with(qapp, ["a.fvf", "b.fvf"])
    panel._comp_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    got = []
    panel.config_ready.connect(got.append)
    panel._save_config()
    assert [os.path.basename(p) for p in got[0]["comp_paths"]] == ["b.fvf"]


def test_adding_same_file_twice_and_clear_all(qapp):
    panel = _panel_with(qapp, ["a.fvf", "a.fvf"])
    assert panel._comp_list.count() == 1
    panel._clear_comps()
    assert panel._comp_list.count() == 0 and panel._comp_summary.text() == ""
    assert panel.get_config()["comp_paths"] == []
