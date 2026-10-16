"""Cross-platform behaviour: font stacks, shortcut naming, headless matplotlib."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import platform_support as ps

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("system", ["Windows", "Darwin", "Linux"])
def test_font_stacks_exist_for_every_platform(monkeypatch, system):
    monkeypatch.setattr(ps.platform, "system", lambda: system)
    assert ps.ui_families()
    assert ps.mono_families()


def test_no_windows_only_font_is_the_sole_choice_on_mac(monkeypatch):
    monkeypatch.setattr(ps.platform, "system", lambda: "Darwin")
    for stack in (ps.ui_families(), ps.mono_families()):
        assert stack[0] not in ("Segoe UI", "Cascadia Code", "Consolas")


def test_mod_key_name(monkeypatch):
    monkeypatch.setattr(ps, "IS_MACOS", True)
    assert ps.mod_key_name() == "Cmd"
    monkeypatch.setattr(ps, "IS_MACOS", False)
    assert ps.mod_key_name() == "Ctrl"


def test_font_builders_return_usable_fonts(qapp):
    ui, mono = ps.ui_font(13), ps.mono_font(10)
    assert ui.families() and mono.families()
    assert mono.fixedPitch()


def test_entrypoint_forces_headless_matplotlib():
    """main.py must pin Agg before pyihm/klassez import pyplot on a QThread (macOS abort)."""
    env = {k: v for k, v in os.environ.items() if k != "MPLBACKEND"}
    env["QT_QPA_PLATFORM"] = "offscreen"
    out = subprocess.run(
        [sys.executable, "-c", "import main, os; print(os.environ['MPLBACKEND'])"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "Agg"


def test_no_hardcoded_windows_fonts_in_python_sources():
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        if path.name == "platform_support.py":
            continue
        text = path.read_text(encoding="utf-8")
        if 'QFont("Segoe UI"' in text or 'QFont("Cascadia Code"' in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, offenders


def test_mac_launcher_is_executable_and_posix():
    launcher = ROOT / "SpectraFlow.command"
    assert launcher.exists()
    assert os.access(launcher, os.X_OK)
    assert b"\r\n" not in launcher.read_bytes()
