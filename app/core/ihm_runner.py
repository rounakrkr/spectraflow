"""Headless IHM pipeline — everything a fit needs, with no Qt.

Both :class:`app.core.engine.AnalysisEngine` (GUI: signals, threads) and the
batch runner (worker *processes*) are built on these functions, so one fit in
the GUI and one fit inside a batch run exactly the same code.

The functions are deliberately small and stateless: each takes what it needs
and returns plain data. Progress, logging and cancellation come in as
callables, so a caller decides whether that means a Qt signal, a ``print`` or
nothing at all.

Importing this module must stay cheap and Qt-free — batch workers import it
in a fresh interpreter.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np
import klassez as kz
import lmfit as l

# pyihm imports — the library stays unchanged
import pyihm.input_reading as pyihm_input
import pyihm.spectra_reading as pyihm_spectra
import pyihm.gen_param as pyihm_gen
import pyihm.fit_mixture as pyihm_fit

LogFn = Callable[[str], None]


def _nolog(_msg: str) -> None:
    pass


class FitCancelled(Exception):
    """Raised from inside a fit to abort it cooperatively."""


# pyihm names each component's intensity parameter ``S<n>_I`` (see
# pyihm.gen_param.main); every other fit parameter is u/s/k/b/U/o.
_INTENSITY_RE = re.compile(r"S\d+_I")


def is_intensity_param(name: str) -> bool:
    """True for a component-intensity parameter (``S1_I``, ``S2_I``, ...)."""
    return _INTENSITY_RE.fullmatch(name) is not None


DEFAULT_BOUNDS = {"utol": 0.2, "utol_sg": 0.1, "stol": 10, "ktol": 0.01}


def with_default_bounds(bds: dict | None) -> dict:
    """``bds`` with every missing tolerance filled in from :data:`DEFAULT_BOUNDS`."""
    out = dict(bds or {})
    for key, value in DEFAULT_BOUNDS.items():
        out.setdefault(key, value)
    return out


def figure_options(plt_opt: dict | None) -> dict:
    """Figure ``ext``/``dpi`` for the exporter from an input file's plot options."""
    opt = plt_opt or {}
    return {"ext": opt.get("ext", "png"), "dpi": opt.get("dpi", 300)}


def normalize_windows(lims) -> list[tuple]:
    """Fit windows as ``(left, right)`` pairs with the high-ppm edge first."""
    return [(max(r), min(r)) for r in lims]


# ── Input files ────────────────────────────────────────────────────
def resolve_input_path(p, base_dir):
    """Resolve a path written in a pyihm input file.

    pyihm itself resolves relative paths against the current working
    directory. A GUI is usually started from somewhere else, so relative
    paths are resolved against the folder of the input file instead
    (falling back to the working directory if only that location exists).
    """
    p = str(p).strip()
    if os.path.isabs(p):
        return os.path.normpath(p)
    candidate = os.path.normpath(os.path.join(base_dir, p))
    if not os.path.exists(candidate) and os.path.exists(p):
        return os.path.abspath(p)
    return candidate


def read_input_file_resolved(path):
    """Parse a pyihm input file and return its settings as a dict,
    with every file path made absolute (see :func:`resolve_input_path`)."""
    ret = pyihm_input.read_input(path)
    (filename, mix_path, mix_kws, mix_txtf, proc_opt,
     comp_path, lims, bds, fit_kws, plt_opt, Hs, I0) = ret

    base = os.path.dirname(os.path.abspath(path))
    return {
        "filename": filename,
        "out_root": resolve_input_path(filename, base),
        "plt_opt": dict(plt_opt),
        "mix_path": resolve_input_path(mix_path, base),
        "mix_kws": mix_kws,
        "mix_txtf": resolve_input_path(mix_txtf, base) if mix_txtf else mix_txtf,
        "proc_opt": proc_opt,
        "comp_path": [resolve_input_path(c, base) for c in comp_path],
        "lims": lims,
        "bds": bds,
        "fit_kws": fit_kws,
        "Hs": Hs,
        "I0": I0,
    }


# ── Step 1: mixture ────────────────────────────────────────────────
def load_mixture(path, mix_kws=None, proc_opt=None, mix_txtf=None):
    """Load and process the mixture spectrum (a ``kz.Spectrum_1D``).

    Follows pyihm's own flow. With ``mix_txtf`` the dataset is only used for
    its acquisition parameters: the spectrum itself is replaced by the
    complex array stored in that text file and the scales are rebuilt to
    match its length.
    """
    M = kz.Spectrum_1D(path, **(mix_kws or {}))

    if mix_txtf:
        M.process()
        spect = np.loadtxt(mix_txtf, dtype="complex128")   # always complex
        M.S = spect
        M.r = spect.real
        M.i = spect.imag
        N = M.r.shape[-1]
        M.freq = kz.processing.make_scale(N, M.acqus["dw"])
        M.ppm = kz.misc.freq2ppm(M.freq, M.acqus["SFO1"], M.acqus["o1p"])
        return M

    # Processing options (pyihm default: all off)
    if proc_opt:
        wf = proc_opt.get("wf", {})
        if isinstance(wf, dict) and wf.get("mode", "no") != "no":
            for key, value in wf.items():
                M.procs[key] = value
        if proc_opt.get("zf"):
            M.procs["zf"] = proc_opt["zf"]
        if proc_opt.get("blp"):
            if isinstance(proc_opt["blp"], dict):
                M.blp(**proc_opt["blp"])
            else:
                M.blp()

    M.process()

    if proc_opt and proc_opt.get("pknl"):
        M.pknl()
    if proc_opt and proc_opt.get("adjph"):
        M.adjph()

    return M


# ── Step 2: components ─────────────────────────────────────────────
def calibrated_variant(path: str) -> str:
    """``<name>-cal<ext>`` — the calibrated copy pyihm's ``--cal`` writes."""
    base, ext = os.path.splitext(path)
    return f"{base}-cal{ext}"


def resolve_calibrated_paths(paths: list[str]) -> list[str]:
    """Swap each component path for its ``-cal`` copy when that file exists."""
    out = []
    for path in paths:
        cal = calibrated_variant(path)
        out.append(cal if os.path.isfile(cal) else path)
    return out


def load_component_set(paths: list[str], acqus: dict, N: int, Hs: list):
    """Read component ``.fvf`` files.

    Returns ``(comp_peaks, components, comp_names)``: per component the dict
    of ``kz.fit.Peak`` objects, the computed spectrum and a display name.
    ``Hs`` normalises each component's peak intensities to its proton count.
    """
    comp_peaks = []
    components = []
    comp_names = []
    for k, path in enumerate(paths):
        peaks_dict, _I = pyihm_spectra.get_component_spectrum(
            path, acqus, return_dict=True, norm=Hs[k], N=N
        )
        spectrum, _ = pyihm_spectra.get_component_spectrum(
            path, acqus, return_dict=False, norm=Hs[k], N=N
        )
        comp_peaks.append(peaks_dict)
        components.append(spectrum)
        comp_names.append(os.path.splitext(os.path.basename(path))[0])
    return comp_peaks, components, comp_names


def intensity_correction(M, acqus: dict, Hs: list) -> float:
    """Theoretical integral of one proton in the mixture spectrum."""
    return kz.processing.integrate(M.r, x=M.freq) / (acqus["SW"] / 2) / np.sum(Hs)


# ── Step 3: fit parameters ─────────────────────────────────────────
def build_parameters(M, comp_peaks, bds, lims, Hs, I0, comp_names, log: LogFn = _nolog):
    """Build ``lmfit.Parameters`` from the loaded components and fit windows.

    Returns ``(param, components, clean_Hs, c_idx, peak_table)``:
    only peaks inside a window are fitted, components without any are
    dropped (``c_idx`` lists the survivors) and ``clean_Hs`` counts protons
    inside the windows only. ``peak_table`` is one row per fitted peak, with
    ``key``/``idx`` locating its lmfit parameters (``S<n>_u<idx>``, ...).
    """
    acqus = dict(M.acqus)

    # Helper: check if chemical shift is within fit regions
    def is_in(x, Bs):
        for B in Bs:
            if min(B) <= x <= max(B):
                return True
        return False

    # Filter peaks to only those within fit regions
    comp_peaks_in = [{} for _ in comp_peaks]
    components = []
    hs_filtered = list(Hs)

    for k, dic_Peaks in enumerate(comp_peaks):
        for key, peak in dic_Peaks.items():
            if is_in(peak.u, lims):
                peak.idx = key
                comp_peaks_in[k][key] = peak
        if len(comp_peaks_in[k]) == 0:
            components.append("Q")
        else:
            components.append(
                pyihm_spectra.Spectr(acqus, *[p for _, p in comp_peaks_in[k].items()])
            )
        # Correct Hs to only count peaks inside fit windows
        Hs_in = np.sum([peak.k for _, peak in comp_peaks_in[k].items()])
        hs_filtered[k] = round(Hs_in, 5)

    # Remove components with no peaks in range
    missing = [i for i, h in enumerate(hs_filtered) if h == 0]
    c_idx = [i for i in range(len(hs_filtered)) if i not in missing]

    clean_components = [c for c in components if c != "Q"]
    clean_Hs = [h for h in hs_filtered if h != 0]
    clean_I0 = [I0[k] for k in c_idx] if I0 else [1.0] * len(clean_components)

    if missing:
        names = [str(m + 1) for m in missing]
        log(f"⚠ Component(s) {', '.join(names)} have no peaks in fit windows")

    param = pyihm_gen.main(M, clean_components, bds, lims, clean_Hs, c_idx, clean_I0)

    # Editable peak table: one row per peak that is actually fitted.
    peak_table = []
    for k in c_idx:
        name = comp_names[k] if k < len(comp_names) else f"component {k + 1}"
        for pk_idx, peak in comp_peaks_in[k].items():
            peak_table.append({
                "u": float(peak.u), "fwhm": float(peak.fwhm), "k": float(peak.k),
                "b": float(peak.b), "phi": float(peak.phi),
                "group": int(peak.group), "group0": int(peak.group),
                "comp": k + 1, "key": f"S{k + 1}_", "idx": pk_idx,
                "label": f"{name} · peak {pk_idx}",
            })

    return param, clean_components, clean_Hs, c_idx, peak_table


# ── Step 4: fit ────────────────────────────────────────────────────
@dataclass
class FitContext:
    """Per-fit constants derived from the mixture and the fit windows."""
    acqus: dict
    N: int
    N_spectra: int
    exp: np.ndarray
    plims: list
    exp_T: np.ndarray


def prepare_fit(M, param, lims) -> FitContext:
    """Convert ppm windows to index slices and slice the experimental data."""
    acqus = dict(M.acqus)
    acqus["freq"] = M.freq
    N = M.r.shape[-1]
    N_spectra = len([k for k in param if is_intensity_param(k)])
    exp = np.copy(M.r)

    # Convert ppm limits to slices
    pts = [tuple([kz.misc.ppmfind(M.ppm, lim)[0] for lim in X]) for X in lims]
    plims = [slice(min(W), max(W)) for W in pts]
    exp_T = np.concatenate([exp[w] for w in plims])
    return FitContext(acqus, N, N_spectra, exp, plims, exp_T)


def minimize(ctx: FitContext, param, I, method: str = "tight", align: bool = True,
             fit_kws: dict | None = None,
             should_cancel: Callable[[], bool] | None = None,
             on_progress: Callable[[int, float], None] | None = None,
             log: LogFn = _nolog):
    """Run the (optionally pre-aligned) minimisation.

    ``should_cancel`` is polled at every residual evaluation and raises
    :class:`FitCancelled` when it returns True. ``on_progress(count, target)``
    is called at every evaluation. Returns ``(lmfit result, history)`` with
    ``history`` a list of ``(count, target)``.
    """
    should_cancel = should_cancel or (lambda: False)
    history: list[tuple[int, float]] = []

    # Add iteration counter
    if "count" in param:
        param["count"].set(value=0)
    else:
        param.add("count", value=0, vary=False)

    # Residual function: reports progress and supports cancellation
    def f2min_gui(param, N_spectra, acqus, N, exp, I, plims):
        if should_cancel():
            raise FitCancelled("Fit cancelled by user")

        param["count"].value += 1
        count = int(param["count"].value)

        spectra = pyihm_fit.calc_spectra(param, N_spectra, acqus, N)
        spectra_T = [np.concatenate([s[w] for w in plims]) for s in spectra]
        total = np.sum(spectra_T, axis=0)
        residual = exp / I - total
        target = np.sum(residual**2) / len(residual)

        history.append((count, float(target)))
        if on_progress is not None:
            on_progress(count, target)

        return residual

    # Pre-alignment (pyihm default, skipped with align=False)
    if align:
        log("Running pre-alignment...")
        try:
            param = pyihm_fit.pre_alignment(
                ctx.exp, ctx.acqus, ctx.N_spectra, ctx.N, ctx.plims, param, False
            )
            param["count"].set(value=0)
            log("Pre-alignment done.")
        except Exception as e:
            log(f"⚠ Pre-alignment skipped: {e}")
    else:
        log("Pre-alignment skipped (disabled).")
    history.clear()

    minner = l.Minimizer(
        f2min_gui, param,
        fcn_args=(ctx.N_spectra, ctx.acqus, ctx.N, ctx.exp_T, I, ctx.plims),
    )

    if method == "fast":
        result = minner.minimize(
            method="leastsq", max_nfev=15000,
            xtol=1e-8, ftol=1e-8, gtol=1e-8,
        )
    elif method == "tight":
        result = minner.minimize(method="Nelder", max_nfev=10000)
        if should_cancel():
            raise FitCancelled("Fit cancelled by user")
        result = minner.minimize(
            method="leastsq", params=result.params,
            max_nfev=10000, xtol=1e-8, ftol=1e-8, gtol=1e-8,
        )
    elif method == "custom" and fit_kws:
        # honour fit_kws from the input file
        for idx in range(len(fit_kws.keys())):
            if should_cancel():
                raise FitCancelled("Fit cancelled by user")
            kws = dict(fit_kws[idx])
            if kws.get("method") == "leastsq":
                tol = kws.pop("tol", 1e-5)
                kws["xtol"] = tol
                kws["ftol"] = tol
                kws["gtol"] = tol
            log(f"Fit round {idx+1}/{len(fit_kws)}: {kws.get('method','leastsq')}")
            if idx != 0:
                kws["params"] = result.params
            result = minner.minimize(**kws)
    else:
        # fallback: leastsq
        result = minner.minimize(
            method="leastsq", max_nfev=15000,
            xtol=1e-8, ftol=1e-8, gtol=1e-8,
        )

    return result, history


def component_numbers(popt, n: int) -> list[int]:
    """1-based component numbers from the ``S<n>_I`` parameter names."""
    try:
        return [int(k.split("_")[0].replace("S", "")) for k in popt if is_intensity_param(k)]
    except ValueError:
        return list(range(1, n + 1))


def x_label(acqus) -> str | None:
    """Axis label for the nucleus in ``acqus`` (``None`` if it can't be built)."""
    try:
        return r"$\delta\ $" + kz.misc.nuc_format(acqus["nuc"]) + r" /ppm"
    except Exception:
        return None


def assemble_results(M, ctx: FitContext, result, I, history, *, c_idx, clean_Hs, Hs,
                     comp_names, lims, mix_path):
    """Turn a finished fit into the results dict used by the GUI and exporter.

    Returns ``(results, opt_spectra, opt_total, c_norm)``.
    """
    popt = result.params
    # Calculate optimized spectra
    opt_spectra = pyihm_fit.calc_spectra(popt, ctx.N_spectra, ctx.acqus, ctx.N)
    opt_spectra_obj = pyihm_fit.calc_spectra_obj(popt, ctx.N_spectra, ctx.acqus, ctx.N)
    opt_total = np.sum(opt_spectra, axis=0)

    # Get concentrations
    Hf = np.array([np.sum([p.k for p in peaks]) for peaks in opt_spectra_obj])
    concentrations = np.array([
        f for key, f in popt.valuesdict().items() if is_intensity_param(key)
    ])
    # use clean_Hs (corrected for fit windows), not nominal Hs
    if clean_Hs and len(clean_Hs) == len(concentrations):
        Hs_used = np.array(clean_Hs)
    elif c_idx:
        Hs_used = np.array([Hs[i] for i in c_idx])
    else:
        Hs_used = np.array(Hs)

    KH = Hf / Hs_used
    concentrations *= KH
    for peaks, kh in zip(opt_spectra_obj, KH):
        for peak in peaks:
            peak.k /= kh
    c_norm, I_corr = kz.misc.molfrac(concentrations)

    results = {
        "ppm": M.ppm,
        "experimental": ctx.exp,
        "total_fit": I * opt_total,
        "components": [I * s for s in opt_spectra],
        "concentrations": list(c_norm),
        "component_names": (
            [comp_names[i] for i in c_idx] if c_idx else comp_names
        ),
        "I": I * I_corr,
        "nfev": result.nfev,
        "message": result.message,
        "Hs": [float(h) for h in Hs_used],
        "peaks": [list(peaks) for peaks in opt_spectra_obj],
        "component_idx": component_numbers(popt, len(c_norm)),
        "lims": [tuple(w) for w in lims],
        "plims": ctx.plims,
        "mixture_path": mix_path,
        "x_label": x_label(ctx.acqus),
        "convergence": list(history),
    }
    return results, opt_spectra, opt_total, c_norm


# ── Whole run, headless ────────────────────────────────────────────
OVERRIDE_KEYS = frozenset({
    "mix_path", "mix_kws", "mix_txtf", "proc_opt", "comp_path",
    "lims", "bds", "fit_kws", "Hs", "I0",
})


def run_ihm(inp_path: str, *, method: str = "tight", align: bool = True,
            out_root: str | None = None, overrides: dict | None = None,
            save: bool = True, use_calibrated: bool = True,
            should_cancel: Callable[[], bool] | None = None,
            on_progress: Callable[[int, float], None] | None = None,
            log: LogFn = _nolog) -> dict:
    """Run one complete IHM analysis from a pyihm input file, with no Qt.

    ``overrides`` replaces settings read from the input file (keys in
    :data:`OVERRIDE_KEYS`); overriding ``mix_path`` also drops the file's
    ``mix_txtf``, which belongs to the original mixture, unless ``mix_txtf``
    is overridden too. This is how one template input is applied to many
    mixtures. Component files are never written, so concurrent runs sharing
    a template cannot race.

    Outputs go to ``out_root`` (default: the input file's own root, or the
    overriding mixture's name next to it) through ``exporter.save_all``.
    Returns a small picklable summary — never the full results dict.
    """
    overrides = dict(overrides or {})
    unknown = set(overrides) - OVERRIDE_KEYS
    if unknown:
        raise ValueError(f"Unknown override(s): {', '.join(sorted(unknown))}")

    t0 = time.perf_counter()
    cfg = read_input_file_resolved(inp_path)
    if "mix_path" in overrides:
        cfg["mix_txtf"] = None
        overrides["mix_path"] = os.path.abspath(str(overrides["mix_path"]))
    cfg.update(overrides)

    mix_path, mix_txtf = cfg["mix_path"], cfg["mix_txtf"]
    if not os.path.exists(mix_path):
        raise FileNotFoundError(f"Mixture spectrum not found: {mix_path}")
    if mix_txtf and not os.path.isfile(str(mix_txtf)):
        raise FileNotFoundError(f"mix_txtf file not found: {mix_txtf}")

    comp_paths = list(cfg["comp_path"] or [])
    if not comp_paths:
        raise ValueError("The input file lists no components")
    if not cfg["lims"]:
        raise ValueError("The input file defines no fit regions")
    lims = normalize_windows(cfg["lims"])
    bds = with_default_bounds(cfg["bds"])

    n = len(comp_paths)
    Hs = list(cfg["Hs"]) if cfg["Hs"] and len(cfg["Hs"]) == n else [1] * n
    if Hs == [1] * n and cfg["Hs"] != Hs:
        log("⚠ Hs not specified — defaulting to [1]*n. Mole fractions may be inaccurate.")
    I0 = list(cfg["I0"]) if cfg["I0"] and len(cfg["I0"]) == n else [1.0] * n

    if out_root is None:
        out_root = cfg["out_root"]
        if "mix_path" in overrides:
            stem = os.path.splitext(os.path.basename(os.path.normpath(mix_path)))[0]
            out_root = os.path.join(os.path.dirname(out_root), stem)

    log(f"Loading mixture {mix_path}")
    M = load_mixture(mix_path, cfg["mix_kws"], cfg["proc_opt"], mix_txtf)
    acqus = dict(M.acqus)
    N = M.r.shape[-1]

    paths = resolve_calibrated_paths(comp_paths) if use_calibrated else comp_paths
    comp_peaks, _components, comp_names = load_component_set(paths, acqus, N, Hs)
    I = intensity_correction(M, acqus, Hs)

    param, _clean, clean_Hs, c_idx, _peak_table = build_parameters(
        M, comp_peaks, bds, lims, Hs, I0, comp_names, log=log
    )
    ctx = prepare_fit(M, param, lims)
    result, history = minimize(
        ctx, param, I, method=method, align=align, fit_kws=cfg["fit_kws"],
        should_cancel=should_cancel, on_progress=on_progress, log=log,
    )
    results, _spectra, _total, _c_norm = assemble_results(
        M, ctx, result, I, history, c_idx=c_idx, clean_Hs=clean_Hs, Hs=Hs,
        comp_names=comp_names, lims=lims, mix_path=mix_path,
    )

    outputs: dict = {}
    if save:
        from app.core import exporter
        outputs = exporter.save_all(out_root, results, **figure_options(cfg["plt_opt"]))

    return {
        "input": os.path.abspath(inp_path),
        "mixture_path": mix_path,
        "out_root": out_root,
        "component_names": list(results["component_names"]),
        "component_idx": [int(c) for c in results["component_idx"]],
        "concentrations": [float(c) for c in results["concentrations"]],
        "I": float(results["I"]),
        "nfev": int(results["nfev"]),
        "message": str(results["message"]),
        "elapsed": time.perf_counter() - t0,
        "outputs": outputs,
    }
