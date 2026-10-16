"""Platform helpers: OS detection and per-OS font choices.

Kept free of side effects at import time so it can be imported before the
QApplication exists (font *families* are plain strings; QFont objects are only
built on request).
"""

from __future__ import annotations

import platform

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"

# First entry that exists on the machine wins (Qt falls back down the list).
_UI_FAMILIES = {
    "Windows": ("Segoe UI", "Inter", "Arial"),
    "Darwin": ("Helvetica Neue", "SF Pro Text", "Arial"),
}
_MONO_FAMILIES = {
    "Windows": ("Cascadia Code", "Consolas", "Courier New"),
    "Darwin": ("SF Mono", "Menlo", "Monaco", "Courier New"),
}
_DEFAULT_UI = ("Inter", "DejaVu Sans", "Arial")
_DEFAULT_MONO = ("DejaVu Sans Mono", "Courier New")


def ui_families() -> tuple[str, ...]:
    return _UI_FAMILIES.get(platform.system(), _DEFAULT_UI)


def mono_families() -> tuple[str, ...]:
    return _MONO_FAMILIES.get(platform.system(), _DEFAULT_MONO)


def ui_font(size: float):
    """Application UI font. Needs a QGuiApplication to exist."""
    from PySide6.QtGui import QFont
    font = QFont()
    font.setFamilies(list(ui_families()))
    font.setPointSizeF(size)
    return font


def mono_font(size: float):
    """Monospace font for logs / terminal / numeric readouts."""
    from PySide6.QtGui import QFont
    font = QFont()
    font.setFamilies(list(mono_families()))
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setPointSizeF(size)
    return font


def mod_key_name() -> str:
    """Name of the primary shortcut modifier as the user sees it on their keyboard."""
    return "Cmd" if IS_MACOS else "Ctrl"
