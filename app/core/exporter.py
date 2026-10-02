"""Write fit results to disk in the same layout pyihm uses.

For an output root ``<dir>/<name>`` the layout is::

    <dir>/<name>.out                  fit report (relative intensities + fitted peaks)
    <dir>/<name>-DATA/<name>-result.csv
    <dir>/<name>-DATA/<name>.cnvg     convergence path
    <dir>/<name>-FIGURES/<name>_*.<ext>
"""

import getpass
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import numpy as np
import klassez as kz

import pyihm.plots as pyihm_plots

DEFAULT_EXT = "png"
DEFAULT_DPI = 300
X_LABEL_FALLBACK = r"$\delta\ $ /ppm"


class ExportError(Exception):
    """Raised when results cannot be exported."""


def _require(results: dict | None) -> dict:
    if not results:
        raise ExportError("No fit results available. Run a fit first.")
    return results


def _lims_pair(results: dict):
    lims = results.get("lims")
    if not lims:
        ppm = np.asarray(results["ppm"])
        return float(np.max(ppm)), float(np.min(ppm))
    arr = np.array(lims, dtype=float)
    return float(arr.max()), float(arr.min())


def split_root(root: str) -> tuple[str, str]:
    """Split an output root into (directory, name); relative roots use the cwd."""
    root = os.path.abspath(root)
    return os.path.dirname(root), os.path.basename(root)


def write_csv(path: str, results: dict) -> str:
    """Write ppm, experimental, total and per-component traces (pyihm ``-result.csv`` layout)."""
    r = _require(results)
    comps = [np.asarray(c) for c in r["components"]]
    header = ["PPM_SCALE", "EXPERIMENTAL", "TOTAL"] + [f"COMPONENT_{k + 1}" for k in range(len(comps))]
    total = np.sum(comps, axis=0) if comps else np.asarray(r["total_fit"])
    columns = [np.asarray(r["ppm"]), np.asarray(r["experimental"]), total] + comps
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    np.savetxt(path, np.array(columns).T, header=" ".join(header), comments="")
    return path


def write_concentrations_csv(path: str, results: dict) -> str:
    """Write the concentration table: component, mole fraction (%), relative to the smallest."""
    r = _require(results)
    conc = np.asarray(r["concentrations"], dtype=float)
    names = r.get("component_names") or [f"Component {i + 1}" for i in range(len(conc))]
    positives = conc[conc > 0]
    c_min = float(positives.min()) if positives.size else None
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("Component,Concentration_percent,Relative\n")
        for name, c in zip(names, conc):
            rel = f"{c / c_min:.5f}" if c_min else ""
            f.write(f"\"{name}\",{c * 100:.5f},{rel}\n")
    return path


def write_report(path: str, results: dict) -> str:
    """Write the pyihm-style fit report (.out) including every fitted peak."""
    r = _require(results)
    peaks = r.get("peaks")
    if not peaks:
        raise ExportError("Fit results contain no peak data for a report.")
    conc = np.asarray(r["concentrations"], dtype=float)
    comp_idx = r.get("component_idx") or list(range(1, len(conc) + 1))
    I_abs = float(r["I"])
    lims = _lims_pair(r)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    positives = conc[conc > 0]
    c_min = float(positives.min()) if positives.size else None
    stamp = datetime.now().strftime("%d/%m/%Y at %H:%M:%S")
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"

    with open(path, "w", buffering=1, encoding="utf-8") as f:
        f.write(f"! Fit performed by {user} on {stamp}\n\n")
        f.write(f"Mixture spectrum: {r.get('mixture_path') or 'unknown'}\n\n")
        f.write(f"Absolute intensity correction: I = {I_abs:.8e}\n\n")
        f.write("Relative intensities:\n")
        for k, frac in enumerate(conc):
            rel = f"{frac / c_min:10.5f}" if c_min else f"{'n/a':>10}"
            f.write(f"Component {comp_idx[k]:>3.0f}: {frac * 100:10.5f}% | Rel: {rel}\n")
        f.write("\n\n\n")

    for k, component in enumerate(peaks):
        dict_component = {j + 1: peak for j, peak in enumerate(component)}
        with open(path, "a", buffering=1, encoding="utf-8") as f:
            f.write(f"Component {comp_idx[k]} fitted parameters:\n")
        kz.fit.write_vf(path, dict_component, lims, conc[k] * I_abs)
        with open(path, "a", buffering=1, encoding="utf-8") as f:
            f.write("\n\n")
    return path


def write_convergence(path: str, history: list) -> str:
    """Write the convergence path as ``step<TAB>target`` lines."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Step \t Target\n")
        for step, target in history:
            f.write(f"{int(step):5d}\t{float(target):10.5e}\n")
    return path


def save_figures(folder: str, name: str, results: dict,
                 ext: str = DEFAULT_EXT, dpi: int = DEFAULT_DPI) -> list[str]:
    """Save the pyihm result figures (total, with components, per-window, convergence)."""
    r = _require(results)
    os.makedirs(folder, exist_ok=True)
    root = os.path.join(folder, name)
    ext = str(ext).lstrip(".").lower() or DEFAULT_EXT
    dpi = int(dpi)

    plims = r.get("plims") or None
    comps = [np.asarray(c) for c in r["components"]]
    try:
        pyihm_plots.plot_output(
            np.asarray(r["ppm"]), np.asarray(r["experimental"]), np.asarray(r["total_fit"]), comps,
            lims=_lims_pair(r), plims=plims,
            X_label=r.get("x_label") or X_LABEL_FALLBACK,
            filename=root, ext=ext, dpi=dpi, windows=bool(plims) and len(plims) > 1,
        )
    finally:
        plt.close("all")

    history = r.get("convergence")
    if history:
        cnvg = write_convergence(os.path.join(folder, f"{name}.cnvg.tmp"), history)
        try:
            pyihm_plots.convergence_path(cnvg, filename=f"{root}_cnvg", ext=ext, dpi=dpi)
        except Exception:
            pass
        finally:
            plt.close("all")
            if os.path.isfile(cnvg):
                os.remove(cnvg)

    return sorted(
        os.path.join(folder, f) for f in os.listdir(folder)
        if f.startswith(name) and f.lower().endswith(f".{ext}")
    )


def save_all(root: str, results: dict, ext: str = DEFAULT_EXT, dpi: int = DEFAULT_DPI) -> dict:
    """Write the complete pyihm output set for ``root`` and return the written paths."""
    r = _require(results)
    base_dir, name = split_root(root)
    data_dir = os.path.join(base_dir, f"{name}-DATA")
    fig_dir = os.path.join(base_dir, f"{name}-FIGURES")
    os.makedirs(data_dir, exist_ok=True)
    out = {"csv": write_csv(os.path.join(data_dir, f"{name}-result.csv"), r)}
    if r.get("peaks"):
        out["report"] = write_report(os.path.join(base_dir, f"{name}.out"), r)
    if r.get("convergence"):
        out["convergence"] = write_convergence(os.path.join(data_dir, f"{name}.cnvg"), r["convergence"])
    out["figures"] = save_figures(fig_dir, name, r, ext=ext, dpi=dpi)
    return out
