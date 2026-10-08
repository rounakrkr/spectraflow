# SpectraFlow

**Modern NMR Mixture Analysis GUI** — Powered by [pyIHM](https://github.com/MetallerTM/pyihm) + [KLASSEZ](https://klassez.readthedocs.io)

A beautiful, modern desktop application for NMR mixture deconvolution using Indirect Hard Modelling (IHM).

## Features

- 🎨 **Modern glassmorphism UI** with dark/light themes (PySide6 + PyQtGraph)
- 📊 **Interactive spectrum viewer** with crosshair, zoom, pan
- 🎚️ **Slider-based controls** — no more clicking dozens of buttons
- 📁 **Folder browser** for component spectra
- 🎯 **Region selector** — drag to define spectral windows
- 🔬 **Calibration panel** — live drift/intensity adjustment
- ⚙️ **Peak editor** — per-peak parameter sliders
- 🚀 **Fit runner** — live convergence monitoring
- 📈 **Results panel** — concentration table, fitted spectrum, residuals
- 💻 **Embedded terminal** with custom commands
- 🪟 **Windows 11 Mica/Acrylic** glass effect support
- ⚡ **Batch processing** — *planned*: the parallel `BatchProcessor` exists but is not yet wired into the GUI

## Tech Stack

- **Python 3.10+** (professor can read/modify)
- **PySide6 (Qt6)** — native C++ rendering, cross-platform
- **PyQtGraph** — GPU-accelerated scientific plotting
- **lmfit** — robust curve fitting
- **pyihm + klassez** — NMR data handling & IHM algorithm

## Quick Start

```bash
# 1. GUI dependencies
pip install PySide6 pyqtgraph numpy lmfit

# 2. NMR backend (install klassez FIRST, then pyihm without dependency resolution)
pip install git+https://github.com/MetallerTM/klassez.git
pip install --no-deps git+https://github.com/MetallerTM/pyihm.git
# pyihm's own klassez>=0.4a.6 pin can't be satisfied by any released klassez
# version, so a plain `pip install pyihm` fails to resolve. Its other
# requirements (nmrglue, csaps, matplotlib, ...) are pulled in by klassez.

# 3. Run
python main.py
```

Run the tests with `pip install -r requirements-dev.txt` (after step 2) and `pytest`.

Or double-click `SpectraFlow.bat` on Windows.

## Project Structure

```
spectraflow/
├── main.py                    # Entry point
├── SpectraFlow.bat            # Windows launcher
├── requirements.txt           # GUI dependencies (+ manual backend install notes)
├── requirements-dev.txt       # pytest
├── app/
│   ├── main_window.py         # Main window (sidebar + panels), wires panels to the engine
│   ├── theme/
│   │   ├── theme_manager.py   # Dark/light theme switching
│   │   ├── dark.qss / light.qss
│   │   └── icons/             # SVG arrows for dropdowns / spinboxes
│   ├── widgets/
│   │   ├── sidebar.py         # Navigation sidebar
│   │   ├── spectrum_viewer.py # PyQtGraph spectrum widget
│   │   ├── parameter_slider.py# Label + slider + spinbox combo
│   │   ├── file_browser.py    # File/folder browser
│   │   ├── terminal.py        # Embedded command terminal
│   │   └── gradient_background.py / gradient_label.py
│   ├── panels/
│   │   ├── dashboard.py       # Welcome screen + stats
│   │   ├── input_config.py    # Input file / component configuration
│   │   ├── spectrum_panel.py  # Interactive spectrum viewer
│   │   ├── region_selector.py # Spectral region picker
│   │   ├── calibration_panel.py # Drift/intensity calibration
│   │   ├── peak_editor.py     # Peak parameter editor
│   │   ├── fit_runner.py      # Fit execution + monitoring
│   │   └── results_panel.py   # Results display + export
│   └── core/
│       ├── engine.py          # AnalysisEngine: wraps the pyihm workflow (load → fit → results)
│       ├── exporter.py        # CSV / report / figure / convergence exports
│       ├── workers.py         # FitWorker, SpectrumLoadWorker, FitCancelled
│       ├── batch_processor.py # Parallel batch runner (not yet wired into the GUI)
│       └── pipeline.py        # Workflow step tracker (currently unused)
└── tests/                     # pytest suite, incl. test_e2e_fit.py (real, unmocked fit)
```

## License

MIT
