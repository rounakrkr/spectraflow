#!/usr/bin/env python3
"""
SpectraFlow — Modern NMR Mixture Analysis GUI
Entry point: python main.py
"""

import sys
import os
import platform

# Ensure PySide6 is used by pyqtgraph
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt

from app.main_window import MainWindow


def enable_windows_backdrop(window, dark: bool = True) -> bool:
    """
    Enable Mica / Acrylic system backdrop on Windows 10/11.
    Returns True if a glass effect was successfully applied.
    """
    if platform.system() != "Windows":
        return False

    try:
        import ctypes
        from ctypes import c_int, byref, sizeof

        hwnd = int(window.winId())
        dwmapi = ctypes.windll.dwmapi

        # ── Dark / light title bar ──────────────────────────
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        val = c_int(1 if dark else 0)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, byref(val), sizeof(val)
        )

        # ── Try Mica Alt first (Win 11 22H2+, subtle) ──────
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        for backdrop_type in (4, 2, 3):
            # 4 = Mica Alt, 2 = Mica, 3 = Acrylic
            val = c_int(backdrop_type)
            result = dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE, byref(val), sizeof(val)
            )
            if result == 0:
                names = {4: "Mica Alt", 2: "Mica", 3: "Acrylic"}
                print(f"[SpectraFlow] Glass effect: {names.get(backdrop_type, '?')} ✓")
                return True

        print("[SpectraFlow] Glass effect: not available (opaque fallback)")
        return False

    except Exception as e:
        print(f"[SpectraFlow] Glass effect: failed ({e})")
        return False


def main():
    app = QApplication(sys.argv)

    # Set default font
    font = QFont("Segoe UI", 13)
    app.setFont(font)

    # App metadata
    app.setApplicationName("SpectraFlow")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("SpectraFlow")

    # Create main window
    window = MainWindow()

    # Force native window handle creation (needed for DWM calls)
    window.winId()

    # Try enabling system glass effect
    has_glass = enable_windows_backdrop(window, dark=True)
    if has_glass:
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    window._has_glass = has_glass  # store for theme toggling

    window.showMaximized()

    # Apply theme after show() so widgets are initialized
    window.apply_initial_theme(app, "dark")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
