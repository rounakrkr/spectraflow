"""
AnalysisEngine — central data-flow controller that wraps the pyihm workflow.

Workflow:  load_mixture → load_components → select_regions → calibrate → gen_params → fit → results

Each step stores its output in self._state and emits a signal so panels can update.
Heavy operations (spectrum loading, fitting) run in QThread workers.
"""

import os
import sys
import traceback
from copy import deepcopy

import numpy as np
import klassez as kz
import lmfit as l

from PySide6.QtCore import QObject, Signal, QThread

# pyihm imports — the library stays unchanged
import pyihm.input_reading as pyihm_input
import pyihm.spectra_reading as pyihm_spectra
import pyihm.gen_param as pyihm_gen
import pyihm.fit_mixture as pyihm_fit


# ── Helper: Background worker ──────────────────────────────────────
class _Worker(QThread):
    """Generic worker that runs a callable in a background thread."""
    finished = Signal(object)   # result
    error = Signal(str)         # error message
    progress = Signal(str)      # status text

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


class AnalysisEngine(QObject):
    """Central controller connecting GUI panels to pyihm backend.

    Stores the analysis state and provides methods for each pipeline step.
    All heavy operations run in background threads; completion is reported
    via signals.
    """

    # ── Signals ─────────────────────────────────────────────
    mixture_loaded = Signal(object, object)       # ppm (ndarray), data (ndarray)
    components_loaded = Signal(list, list)         # list[ndarray], list[str] (names)
    regions_set = Signal(list)                     # list of (left, right) tuples
    calibration_done = Signal(list, list)          # drifts, intensities
    params_ready = Signal(object)                  # lmfit.Parameters
    fit_progress = Signal(int, float)              # iteration, target
    fit_finished = Signal(dict)                    # full results dict
    error = Signal(str, str)                       # step, message
    log = Signal(str)                              # status message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = {}
        self._worker = None  # current background worker
        self.reset()

    def reset(self):
        """Clear all state for a fresh analysis."""
        self._state = {
            "M": None,               # kz.Spectrum_1D — mixture spectrum
            "acqus": None,            # dict — acquisition parameters
            "ppm": None,              # ndarray — ppm scale
            "exp": None,              # ndarray — experimental spectrum (real part)
            "comp_paths": [],         # list[str] — paths to .fvf files
            "comp_peaks": [],         # list[dict] — peak dicts per component
            "components": [],         # list[ndarray] — computed component spectra
            "comp_names": [],         # list[str] — component display names
            "Hs": [],                # list[float] — nominal integrals
            "I0": None,               # list or None — initial concentrations
            "I": None,                # float — intensity correction
            "lims": None,             # list[tuple] — fit regions (ppm)
            "bds": {},                # dict — fit boundaries
            "fit_kws": {},            # dict — fit keyword args
            "param": None,            # lmfit.Parameters
            "result": None,           # lmfit result
            "c_idx": None,            # list — component indices used in fit
            "concentrations": None,   # ndarray — final concentrations
            "opt_spectra": None,      # list[ndarray] — optimized component spectra
            "opt_total": None,        # ndarray — total fit
        }

    # ── Accessors ───────────────────────────────────────────
    @property
    def mixture(self):
        return self._state["M"]

    @property
    def ppm(self):
        return self._state["ppm"]

    @property
    def experimental(self):
        return self._state["exp"]

    @property
    def acqus(self):
        return self._state["acqus"]

    @property
    def components(self):
        return self._state["components"]

    @property
    def comp_names(self):
        return self._state["comp_names"]

    @property
    def has_mixture(self) -> bool:
        return self._state["M"] is not None

    @property
    def has_components(self) -> bool:
        return len(self._state["components"]) > 0

    @property
    def has_regions(self) -> bool:
        return self._state["lims"] is not None

    # ── Step 1: Load mixture ───────────────────────────────
    def load_mixture(self, path: str, mix_kws: dict | None = None,
                     proc_opt: dict | None = None):
        """Load the mixture spectrum from a Bruker/NMR directory.

        Runs in background thread. Emits mixture_loaded(ppm, data) on success.
        """
        self.log.emit(f"Loading mixture from {path}...")

        def _do_load():
            kws = mix_kws or {}
            M = kz.Spectrum_1D(path, **kws)
            acqus = dict(M.acqus)

            # Process
            if proc_opt:
                for key, value in proc_opt.get("wf", {}).items():
                    M.procs[key] = value
                if proc_opt.get("zf"):
                    M.procs["zf"] = proc_opt["zf"]
                if proc_opt.get("blp"):
                    M.blp(**proc_opt["blp"])

            M.process()

            if proc_opt and proc_opt.get("pknl"):
                M.pknl()
            if proc_opt and proc_opt.get("adjph"):
                M.adjph()

            N = M.r.shape[-1]
            M.freq = kz.processing.make_scale(N, acqus["dw"])
            M.ppm = kz.misc.freq2ppm(M.freq, acqus["SFO1"], acqus["o1p"])

            return M

        def _on_done(M):
            self._state["M"] = M
            self._state["acqus"] = dict(M.acqus)
            self._state["ppm"] = M.ppm
            self._state["exp"] = np.copy(M.r)
            self.log.emit(f"Mixture loaded: {M.r.shape[-1]} points, "
                          f"ppm range [{M.ppm.min():.2f}, {M.ppm.max():.2f}]")
            self.mixture_loaded.emit(M.ppm, M.r)

        self._run_worker(_do_load, _on_done, "load_mixture")

    def load_mixture_txt(self, path: str):
        """Load a mixture spectrum from a simple 2-column text file.

        For quick testing or when Bruker data isn't available.
        Emits mixture_loaded(ppm, data) on success.
        """
        self.log.emit(f"Loading text spectrum from {path}...")

        def _do_load():
            arr = np.loadtxt(path)
            if arr.ndim == 1:
                raise ValueError("File must have 2 columns (ppm, intensity)")
            return arr[:, 0], arr[:, 1]

        def _on_done(result):
            ppm, data = result
            self._state["ppm"] = ppm
            self._state["exp"] = data
            self._state["acqus"] = None  # no acqus for text files
            self._state["M"] = None
            self.log.emit(f"Text spectrum loaded: {len(ppm)} points")
            self.mixture_loaded.emit(ppm, data)

        self._run_worker(_do_load, _on_done, "load_mixture_txt")

    # ── Step 2: Load components ────────────────────────────
    def load_components(self, comp_paths: list[str], Hs: list | None = None):
        """Load component .fvf files and compute their spectra.

        Requires mixture to be loaded first (needs acqus/N).
        Emits components_loaded(list[ndarray], list[str]) on success.
        """
        if not self.has_mixture:
            self.error.emit("load_components", "Load mixture spectrum first")
            return

        self.log.emit(f"Loading {len(comp_paths)} components...")

        M = self._state["M"]
        acqus = dict(M.acqus)
        N = M.r.shape[-1]

        if Hs is None:
            Hs = [1] * len(comp_paths)

        def _do_load():
            comp_peaks = []
            components = []
            comp_names = []

            for k, path in enumerate(comp_paths):
                peaks_dict, I = pyihm_spectra.get_component_spectrum(
                    path, acqus, return_dict=True, norm=Hs[k], N=N
                )
                spectrum, _ = pyihm_spectra.get_component_spectrum(
                    path, acqus, return_dict=False, norm=Hs[k], N=N
                )
                comp_peaks.append(peaks_dict)
                components.append(spectrum)
                comp_names.append(os.path.splitext(os.path.basename(path))[0])

            return comp_peaks, components, comp_names

        def _on_done(result):
            comp_peaks, components, comp_names = result
            self._state["comp_paths"] = list(comp_paths)
            self._state["comp_peaks"] = comp_peaks
            self._state["components"] = components
            self._state["comp_names"] = comp_names
            self._state["Hs"] = list(Hs)

            # Compute initial intensity correction
            M = self._state["M"]
            acqus = dict(M.acqus)
            I = kz.processing.integrate(M.r, x=M.freq) / (acqus["SW"] / 2) / np.sum(Hs)
            self._state["I"] = I
            self._state["I0"] = [1.0] * len(components)

            self.log.emit(f"Loaded {len(components)} components: {', '.join(comp_names)}")
            self.components_loaded.emit(components, comp_names)

        self._run_worker(_do_load, _on_done, "load_components")

    # ── Step 3: Set fit regions ────────────────────────────
    def set_regions(self, regions: list[tuple]):
        """Set the spectral regions for fitting.

        Each region is a (left_ppm, right_ppm) tuple.
        Emits regions_set(list[tuple]).
        """
        # Ensure left > right (NMR convention: high ppm = left)
        lims = [(max(r), min(r)) for r in regions]
        self._state["lims"] = lims
        self.log.emit(f"Fit regions set: {len(lims)} windows")
        self.regions_set.emit(lims)

    # ── Step 4: Set fit boundaries ─────────────────────────
    def set_boundaries(self, bds: dict):
        """Set parameter boundaries for the fit.

        Expected keys: utol, utol_sg, stol, ktol
        """
        defaults = {"utol": 0.2, "utol_sg": 0.1, "stol": 10, "ktol": 0.01}
        for key, val in defaults.items():
            if key not in bds:
                bds[key] = val
        self._state["bds"] = bds
        self.log.emit(f"Boundaries set: utol={bds['utol']}, stol={bds['stol']}")

    # ── Step 5: Generate parameters ────────────────────────
    def generate_params(self):
        """Build lmfit.Parameters from the loaded components and regions.

        Requires: mixture, components, regions, boundaries.
        Emits params_ready(lmfit.Parameters).
        """
        M = self._state["M"]
        lims = self._state["lims"]
        bds = self._state["bds"]
        Hs = self._state["Hs"]
        comp_peaks = self._state["comp_peaks"]
        I0 = self._state["I0"]

        if M is None or not comp_peaks or lims is None:
            self.error.emit("generate_params", "Complete previous steps first")
            return

        self.log.emit("Generating fit parameters...")

        def _do_gen():
            acqus = dict(M.acqus)
            N = M.r.shape[-1]

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
                # Correct Hs
                Hs_in = np.sum([peak.k for _, peak in comp_peaks_in[k].items()])
                hs_filtered[k] = round(Hs_in, 5)

            # Remove components with no peaks in range
            missing = [i for i, h in enumerate(hs_filtered) if h == 0]
            c_idx = [i for i in range(len(hs_filtered)) if i not in missing]

            clean_components = [c for c in components if c != "Q"]
            clean_Hs = [h for h in hs_filtered if h != 0]
            clean_I0 = [I0[k] for k in c_idx] if I0 else [1.0] * len(clean_components)

            # Generate parameters
            param = pyihm_gen.main(M, clean_components, bds, lims, clean_Hs, c_idx, clean_I0)

            return param, clean_components, clean_Hs, c_idx

        def _on_done(result):
            param, components, Hs, c_idx = result
            self._state["param"] = param
            self._state["c_idx"] = c_idx
            n_vary = len([p for p in param if param[p].vary])
            self.log.emit(f"Parameters ready: {n_vary} free parameters")
            self.params_ready.emit(param)

        self._run_worker(_do_gen, _on_done, "generate_params")

    # ── Step 6: Run fit ────────────────────────────────────
    def run_fit(self, method: str = "tight"):
        """Run the IHM fit in a background thread.

        Emits fit_progress(iteration, target) during iteration,
        and fit_finished(results_dict) on completion.
        """
        M = self._state["M"]
        param = self._state["param"]
        lims = self._state["lims"]
        I = self._state["I"]
        Hs = self._state["Hs"]

        if M is None or param is None:
            self.error.emit("run_fit", "Generate parameters first")
            return

        self.log.emit(f"Starting fit (method={method})...")

        acqus = dict(M.acqus)
        acqus["freq"] = M.freq
        N = M.r.shape[-1]
        N_spectra = len([k for k in param if "I" in k])
        exp = np.copy(M.r)

        # Convert ppm limits to slices
        pts = [tuple([kz.misc.ppmfind(M.ppm, lim)[0] for lim in X]) for X in lims]
        plims = [slice(min(W), max(W)) for W in pts]
        exp_T = np.concatenate([exp[w] for w in plims])

        def _do_fit():
            # Add iteration counter
            param.add("count", value=0, vary=False)

            # Custom f2min that emits progress signal
            def f2min_gui(param, N_spectra, acqus, N, exp, I, plims):
                param["count"].value += 1
                count = int(param["count"].value)

                spectra = pyihm_fit.calc_spectra(param, N_spectra, acqus, N)
                spectra_T = [np.concatenate([s[w] for w in plims]) for s in spectra]
                total = np.sum(spectra_T, axis=0)
                residual = exp / I - total
                target = np.sum(residual**2) / len(residual)

                # Emit progress every 5 iterations
                if count % 5 == 0:
                    self.fit_progress.emit(count, target)

                return residual

            minner = l.Minimizer(
                f2min_gui, param,
                fcn_args=(N_spectra, acqus, N, exp_T, I, plims),
            )

            if method == "fast":
                result = minner.minimize(
                    method="leastsq", max_nfev=15000,
                    xtol=1e-8, ftol=1e-8, gtol=1e-8,
                )
            elif method == "tight":
                result = minner.minimize(method="Nelder", max_nfev=10000)
                result = minner.minimize(
                    method="leastsq", params=result.params,
                    max_nfev=10000, xtol=1e-8, ftol=1e-8, gtol=1e-8,
                )
            else:
                result = minner.minimize(
                    method="leastsq", max_nfev=15000,
                    xtol=1e-8, ftol=1e-8, gtol=1e-8,
                )

            return result

        def _on_done(result):
            popt = result.params
            # Calculate optimized spectra
            opt_spectra = pyihm_fit.calc_spectra(popt, N_spectra, acqus, N)
            opt_spectra_obj = pyihm_fit.calc_spectra_obj(popt, N_spectra, acqus, N)
            opt_total = np.sum(opt_spectra, axis=0)

            # Get concentrations
            Hf = np.array([np.sum([p.k for p in peaks]) for peaks in opt_spectra_obj])
            concentrations = np.array([
                f for key, f in popt.valuesdict().items() if "I" in key
            ])
            # Apply intensity correction
            c_idx = self._state["c_idx"]
            Hs_used = [self._state["Hs"][i] for i in c_idx] if c_idx else self._state["Hs"]
            KH = Hf / np.array(Hs_used)
            concentrations *= KH
            c_norm, I_corr = kz.misc.molfrac(concentrations)

            self._state["result"] = result
            self._state["opt_spectra"] = opt_spectra
            self._state["opt_total"] = opt_total
            self._state["concentrations"] = c_norm

            results_dict = {
                "ppm": M.ppm,
                "experimental": exp,
                "total_fit": I * opt_total,
                "components": [I * s for s in opt_spectra],
                "concentrations": list(c_norm),
                "component_names": [self._state["comp_names"][i] for i in c_idx] if c_idx else self._state["comp_names"],
                "I": I * I_corr,
                "nfev": result.nfev,
                "message": result.message,
            }

            self.log.emit(f"Fit complete: {result.nfev} evaluations")
            self.fit_finished.emit(results_dict)

        self._run_worker(_do_fit, _on_done, "run_fit")

    # ── Step 7: Load from input file ───────────────────────
    def load_input_file(self, path: str):
        """Parse a pyihm input file and populate all state at once.

        This is the 'load everything from a text input file' path —
        the same workflow as `python -m pyihm --input <file>`.
        """
        self.log.emit(f"Reading input file: {path}")

        def _do_load():
            ret = pyihm_input.read_input(path)
            filename, mix_path, mix_kws, mix_txtf, proc_opt, comp_path, lims, bds, fit_kws, plt_opt, Hs, I0 = ret
            return {
                "filename": filename,
                "mix_path": mix_path,
                "mix_kws": mix_kws,
                "mix_txtf": mix_txtf,
                "proc_opt": proc_opt,
                "comp_path": comp_path,
                "lims": lims,
                "bds": bds,
                "fit_kws": fit_kws,
                "Hs": Hs,
                "I0": I0,
            }

        def _on_done(parsed):
            self._state["bds"] = parsed["bds"]
            self._state["fit_kws"] = parsed["fit_kws"]
            self._state["I0"] = parsed["I0"]
            self._state["Hs"] = parsed["Hs"]
            self._state["comp_paths"] = parsed["comp_path"]

            if parsed["lims"]:
                self._state["lims"] = [(max(r), min(r)) for r in parsed["lims"]]

            self.log.emit("Input file parsed. Loading mixture spectrum...")

            # Chain: load mixture → load components
            self.load_mixture(
                parsed["mix_path"],
                mix_kws=parsed["mix_kws"],
                proc_opt=parsed["proc_opt"],
            )

        self._run_worker(_do_load, _on_done, "load_input_file")

    # ── Calibration helpers ────────────────────────────────
    def apply_drift(self, comp_idx: int, drift_ppm: float):
        """Apply a chemical-shift drift correction to a single component."""
        if comp_idx >= len(self._state["comp_peaks"]):
            return
        for _, peak in self._state["comp_peaks"][comp_idx].items():
            peak.u += drift_ppm
        # Recompute the component spectrum
        M = self._state["M"]
        acqus = dict(M.acqus)
        N = M.r.shape[-1]
        spectrum = np.sum([peak() for _, peak in self._state["comp_peaks"][comp_idx].items()], axis=0)
        self._state["components"][comp_idx] = spectrum
        self.log.emit(f"Applied drift of {drift_ppm:.4f} ppm to component {comp_idx + 1}")

    def set_initial_concentration(self, comp_idx: int, value: float):
        """Set the initial guess for a component's concentration."""
        if self._state["I0"] is None:
            self._state["I0"] = [1.0] * len(self._state["components"])
        if comp_idx < len(self._state["I0"]):
            self._state["I0"][comp_idx] = value

    # ── Internal ───────────────────────────────────────────
    def _run_worker(self, fn, on_done, step_name: str):
        """Launch a background worker, routing signals."""
        worker = _Worker(fn)
        worker.finished.connect(on_done)
        worker.error.connect(lambda msg: self.error.emit(step_name, msg))
        worker.finished.connect(lambda _: worker.deleteLater())
        worker.error.connect(lambda _: worker.deleteLater())
        # Store reference to prevent GC
        self._worker = worker
        worker.start()
