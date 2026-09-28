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
- ⚡ **Batch processing** — 100+ mixtures in parallel

## Tech Stack

- **Python 3.10+** (professor can read/modify)
- **PySide6 (Qt6)** — native C++ rendering, cross-platform
- **PyQtGraph** — GPU-accelerated scientific plotting
- **lmfit** — robust curve fitting
- **pyihm + klassez** — NMR data handling & IHM algorithm

## Quick Start

```bash
# Install dependencies
pip install PySide6 pyqtgraph numpy lmfit

# Run
python main.py
```

Or double-click `SpectraFlow.bat` on Windows.

## Project Structure

```
spectraflow/
├── main.py                    # Entry point
├── SpectraFlow.bat            # Windows launcher
├── requirements.txt           # Dependencies
├── app/
│   ├── __init__.py
│   ├── main_window.py         # Main window (sidebar + panels)
│   ├── theme/
│   │   ├── theme_manager.py   # Dark/light theme switching
│   │   ├── dark.qss           # Modern dark theme (glassmorphism)
│   │   └── light.qss          # Light theme
│   ├── widgets/
│   │   ├── sidebar.py         # Navigation sidebar
│   │   ├── spectrum_viewer.py # PyQtGraph spectrum widget
│   │   ├── parameter_slider.py# Label + slider + spinbox combo
│   │   ├── file_browser.py    # File/folder browser
│   │   └── terminal.py        # Embedded command terminal
│   ├── panels/
│   │   ├── dashboard.py       # Welcome screen + stats
│   │   ├── input_config.py    # Input file configuration
│   │   ├── spectrum_panel.py  # Interactive spectrum viewer
│   │   ├── region_selector.py # Spectral region picker
│   │   ├── calibration_panel.py # Drift/intensity calibration
│   │   ├── peak_editor.py     # Peak parameter editor
│   │   ├── fit_runner.py      # Fit execution + monitoring
│   │   └── results_panel.py   # Results display + export
│   └── core/
│       ├── pipeline.py        # Workflow state management
│       ├── workers.py         # Background thread workers
│       └── batch_processor.py # Parallel batch processing
```

## License

MIT
