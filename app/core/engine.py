"""
AnalysisEngine — central data-flow controller that wraps the pyihm workflow.

Workflow:  load_mixture → load_components → calibrate → select_regions → gen_params → fit → results

Each step stores its output in self._state and emits a signal so panels can update.
Heavy operations (spectrum loading, fitting) run in QThread workers.

FIX LOG (v2):
  #1  Flow order: calibrate BEFORE regions → params. generate_params() is NOT
      auto-triggered by regions_set; it is triggered by the caller (main_window)
      after calibration is done.
  #2  clean_Hs saved back to state in generate_params._on_done.
  #3  .inp file: load_input_file chains mixture → components → regions fully.
      mix_txtf handled.  fit_kws honoured for 'custom' method.
  #4  load_components preserves existing I0 / Hs from state (set by .inp file).
  #5  Pre-alignment fit added (pyihm default).  -cal.fvf probed automatically.
  #6  Worker signal renamed to 'completed' to avoid shadowing QThread.finished.
      Fit cancellation via threading.Event.
  #7  requirements.txt updated (separate commit).
"""

import os
import threading
import traceback

import numpy as np
import klassez as kz

from PySide6.QtCore import QObject, Signal, QThread

from app.core import ihm_runner as ihm
# The pipeline helpers moved to the Qt-free ``ihm_runner`` (shared with the
# batch workers); they stay importable from here.
from app.core.ihm_runner import (  # noqa: F401
    FitCancelled, is_intensity_param, resolve_input_path, read_input_file_resolved,
)

# Callers/tests patch pyihm through ``engine.pyihm_fit``. It is the very module
# object ``ihm_runner`` calls, so a patch made here reaches the fit as well.
pyihm_fit = ihm.pyihm_fit


# ── Helper: Background worker ──────────────────────────────────────
class _Worker(QThread):
    """Generic worker that runs a callable in a background thread.

    Uses 'completed' (not 'finished') to avoid shadowing QThread.finished.
    """
    completed = Signal(object)   # result        (#6 fix: renamed)
    failed = Signal(str)         # error message  (#6 fix: renamed)
    cancelled = Signal()         # fn raised FitCancelled — user action, not an error
    progress = Signal(str)       # status text

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.completed.emit(result)
        except FitCancelled:
            self.cancelled.emit()
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


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
    fit_cancelled = Signal()                       # fit stopped by the user (not an error)
    peaks_ready = Signal(list)                     # editable peak table (see generate_params)
    error = Signal(str, str)                       # step, message
    log = Signal(str)                              # status message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = {}
        self._workers = []       # prevent GC, allow multiple concurrent workers
        self._cancel = threading.Event()
        self.reset()

    def reset(self):
        """Clear all state for a fresh analysis (a fit still running is cancelled)."""
        self._cancel.set()
        self._cancel = threading.Event()
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
            "clean_Hs": None,         # list — corrected Hs for fit windows  (#2 fix)
            "concentrations": None,   # ndarray — final concentrations
            "opt_spectra": None,      # list[ndarray] — optimized component spectra
            "opt_total": None,        # ndarray — total fit
            "mix_path": None,         # str — mixture spectrum location (for the report)
            "mix_kws": {},            # dict — kwargs the mixture was loaded with
            "proc_opt": None,         # dict — processing options the mixture was loaded with
            "mix_txtf": None,         # str — text spectrum that replaced the mixture, if any
            "out_root": None,         # str — output root from the input file (no extension)
            "plt_opt": {},            # dict — figure format / dpi from the input file
            "drifts": [],             # list[float] — chemical-shift drift applied per component
            "results": None,          # dict — last fit_finished payload
            "peak_table": [],         # list[dict] — peaks inside the fit windows (editor)
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
                     proc_opt: dict | None = None, mix_txtf: str | None = None):
        """Load the mixture spectrum from a Bruker/NMR directory.

        With ``mix_txtf`` the spectrum is replaced by the complex array stored
        in that text file (pyihm's ``mix_txtf``); the directory still supplies
        the acquisition parameters.

        Runs in background thread. Emits mixture_loaded(ppm, data) on success.
        """
        self.log.emit(f"Loading mixture from {path}...")

        def _do_load():
            return ihm.load_mixture(path, mix_kws, proc_opt, mix_txtf)

        def _on_done(M):
            self._state["M"] = M
            self._state["mix_path"] = path
            self._state["mix_kws"] = dict(mix_kws or {})
            self._state["proc_opt"] = proc_opt
            self._state["mix_txtf"] = mix_txtf
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
            self._state["acqus"] = None
            self._state["M"] = None
            self._state["mix_path"] = path
            self.log.emit(f"Text spectrum loaded: {len(ppm)} points")
            self.mixture_loaded.emit(ppm, data)

        self._run_worker(_do_load, _on_done, "load_mixture_txt")

    # ── Step 2: Load components ────────────────────────────
    def load_components(self, comp_paths: list[str], Hs: list | None = None):
        """Load component .fvf files and compute their spectra.

        Requires mixture to be loaded first (needs acqus/N).
        Emits components_loaded(list[ndarray], list[str]) on success.

        FIX #4: If Hs/I0 already set in state (e.g. from .inp file), those are
        preserved — not overwritten with defaults.
        FIX #5: Probes for -cal.fvf files and uses them if found.
        """
        if not self.has_mixture:
            self.error.emit("load_components", "Load mixture spectrum first")
            return

        self.log.emit(f"Loading {len(comp_paths)} components...")

        M = self._state["M"]
        acqus = dict(M.acqus)
        N = M.r.shape[-1]

        # FIX #4: use state Hs if already set (e.g. from .inp file), else param, else default
        if Hs is not None:
            use_Hs = list(Hs)
        elif self._state["Hs"] and len(self._state["Hs"]) == len(comp_paths):
            use_Hs = list(self._state["Hs"])
        else:
            use_Hs = [1] * len(comp_paths)
            self.log.emit("⚠ Hs not specified — defaulting to [1]*n. "
                          "Mole fractions may be inaccurate.")

        # FIX #5: probe for -cal.fvf files
        actual_paths = ihm.resolve_calibrated_paths(comp_paths)
        for orig, actual in zip(comp_paths, actual_paths):
            if actual != orig:
                self.log.emit(f"Using calibrated: {os.path.basename(actual)}")

        def _do_load():
            return ihm.load_component_set(actual_paths, acqus, N, use_Hs)

        def _on_done(result):
            comp_peaks, components, comp_names = result
            self._state["comp_paths"] = list(actual_paths)
            self._state["comp_peaks"] = comp_peaks
            self._state["components"] = components
            self._state["comp_names"] = comp_names
            self._state["Hs"] = list(use_Hs)
            self._state["drifts"] = [0.0] * len(components)

            # Compute initial intensity correction
            M = self._state["M"]
            I = ihm.intensity_correction(M, acqus, use_Hs)
            self._state["I"] = I

            # FIX #4: only set I0 to defaults if not already populated
            if self._state["I0"] is None or len(self._state["I0"]) != len(components):
                self._state["I0"] = [1.0] * len(components)

            self.log.emit(f"Loaded {len(components)} components: {', '.join(comp_names)}")
            self.components_loaded.emit(components, comp_names)

        self._run_worker(_do_load, _on_done, "load_components")

    # ── Step 3: Set fit regions ────────────────────────────
    def set_regions(self, regions: list[tuple]):
        """Set the spectral regions for fitting.

        Each region is a (left_ppm, right_ppm) tuple.
        Emits regions_set(list[tuple]).

        FIX #1: Does NOT auto-trigger generate_params().
        The caller (main_window) decides when to generate params
        (after calibration is done).
        """
        # Ensure left > right (NMR convention: high ppm = left)
        lims = ihm.normalize_windows(regions)
        self._state["lims"] = lims
        # Parameters and peaks were built for the previous windows; keeping them
        # would fit new windows with peaks selected for the old ones.
        self._state["param"] = None
        self._state["c_idx"] = None
        self._state["clean_Hs"] = None
        self._state["peak_table"] = []
        self.log.emit(f"Fit regions set: {len(lims)} windows")
        self.regions_set.emit(lims)

    # ── Step 4: Set fit boundaries ─────────────────────────
    def set_boundaries(self, bds: dict):
        """Set parameter boundaries for the fit.

        Expected keys: utol, utol_sg, stol, ktol
        """
        for key, val in ihm.DEFAULT_BOUNDS.items():
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

        if not bds:
            # Auto-set defaults if caller forgot
            self.set_boundaries({})
            bds = self._state["bds"]

        self.log.emit("Generating fit parameters...")
        comp_names = list(self._state["comp_names"])

        def _do_gen():
            return ihm.build_parameters(
                M, comp_peaks, bds, lims, Hs, I0, comp_names, log=self.log.emit
            )

        def _on_done(result):
            param, components, clean_Hs, c_idx, peak_table = result
            self._state["peak_table"] = peak_table
            self._state["param"] = param
            self._state["c_idx"] = c_idx
            # FIX #2: save corrected Hs so concentration calc uses them
            self._state["clean_Hs"] = clean_Hs
            n_vary = len([p for p in param if param[p].vary])
            self.log.emit(f"Parameters ready: {n_vary} free parameters")
            self.params_ready.emit(param)
            self.peaks_ready.emit([dict(p) for p in peak_table])

        self._run_worker(_do_gen, _on_done, "generate_params")

    # ── Step 6: Run fit ────────────────────────────────────
    def run_fit(self, method: str = "tight", align: bool = True):
        """Run the IHM fit in a background thread.

        Emits fit_progress(iteration, target) during iteration,
        and fit_finished(results_dict) on completion.

        FIX #3: Supports 'custom' method using state fit_kws.
        FIX #5: Runs pre-alignment by default (like pyihm); ``align=False``
        skips it (pyihm's ``--noalgn``).
        FIX #6: Cancel via self._cancel event; stop button actually works.
        """
        M = self._state["M"]
        param = self._state["param"]
        lims = self._state["lims"]
        I = self._state["I"]
        fit_kws = self._state.get("fit_kws", {})

        if M is None or param is None:
            self.error.emit("run_fit", "Generate parameters first")
            return

        # A fresh event per run: an old, still-unwinding worker keeps its own
        # (set) event, so Stop → Start can never un-cancel it.
        self._cancel = threading.Event()
        self.log.emit(f"Starting fit (method={method})...")

        ctx = ihm.prepare_fit(M, param, lims)
        cancel_event = self._cancel  # local ref for closure

        def _on_progress(count, target):
            # Emit progress every 5 iterations
            if count % 5 == 0:
                self.fit_progress.emit(count, target)

        def _do_fit():
            return ihm.minimize(
                ctx, param, I, method=method, align=align, fit_kws=fit_kws,
                should_cancel=cancel_event.is_set,
                on_progress=_on_progress, log=self.log.emit,
            )

        def _on_cancel():
            if cancel_event is not self._cancel:
                return        # a newer fit has started; this is a stale notification
            self.log.emit("Fit cancelled.")
            self.fit_cancelled.emit()

        def _on_done(outcome):
            result, history = outcome
            if cancel_event.is_set():       # Stop arrived just as the fit finished
                _on_cancel()
                return
            results_dict, opt_spectra, opt_total, c_norm = ihm.assemble_results(
                M, ctx, result, I, history,
                c_idx=self._state["c_idx"],
                clean_Hs=self._state.get("clean_Hs"),
                Hs=self._state["Hs"],
                comp_names=self._state["comp_names"],
                lims=lims,
                mix_path=self._state.get("mix_path"),
            )

            self._state["result"] = result
            self._state["opt_spectra"] = opt_spectra
            self._state["opt_total"] = opt_total
            self._state["concentrations"] = c_norm
            self._state["results"] = results_dict

            self.log.emit(f"Fit complete: {result.nfev} evaluations")
            self.fit_finished.emit(results_dict)

        self._run_worker(_do_fit, _on_done, "run_fit", on_cancel=_on_cancel)

    @staticmethod
    def _component_numbers(popt, n: int) -> list[int]:
        """1-based component numbers from the ``S<n>_I`` parameter names."""
        return ihm.component_numbers(popt, n)

    @staticmethod
    def _x_label(acqus) -> str | None:
        return ihm.x_label(acqus)

    def apply_peak_edits(self, peaks: list[dict]) -> dict:
        """Write edited peak values back into the fit's starting parameters.

        Position, linewidth, intensity and Gaussian fraction of peaks that came
        from :attr:`peaks_ready` are applied (bounds are widened/shifted so the
        new start value is feasible). Phase and group edits are preview-only
        (pyihm does not fit them) and peaks added in the editor have no
        parameters to map to; both are counted, not silently dropped.
        """
        param = self._state["param"]
        if param is None:
            self.error.emit("apply_peak_edits", "Generate parameters first")
            return {"applied": 0, "added_ignored": 0, "phase_ignored": 0}

        lims = self._state["lims"] or []
        applied = added = phase = 0
        for p in peaks:
            key, idx = p.get("key"), p.get("idx")
            if key is None:
                added += 1
                continue
            names = {c: f"{key}{c}{idx}" for c in "uskb"}
            if any(n not in param for n in names.values()):
                added += 1
                continue

            self._set_start_value(param[names["s"]], max(float(p["fwhm"]), 0.0))
            self._set_start_value(param[names["k"]], max(float(p["k"]), 0.0))
            self._set_start_value(param[names["b"]], min(max(float(p["b"]), 0.0), 1.0))

            u_new = float(p["u"])
            u_par = param[names["u"]]
            if u_par.expr:                      # multiplet line: u = U + o
                U_par = param.get(f"{key}U{p.get('group0', p.get('group', 0))}")
                o_par = param.get(f"{key}o{idx}")
                if U_par is not None and o_par is not None:
                    self._set_start_value(o_par, u_new - float(U_par.value))
            else:
                self._shift_start_value(u_par, u_new, lims)
            applied += 1
            if abs(float(p.get("phi", 0.0))) > 1e-9:
                phase += 1

        self.log.emit(f"Peak edits applied to {applied} peak(s)"
                      + (f"; {added} added peak(s) ignored (no fit parameters)" if added else "")
                      + (f"; phase of {phase} peak(s) is preview-only" if phase else ""))
        return {"applied": applied, "added_ignored": added, "phase_ignored": phase}

    @staticmethod
    def _set_start_value(par, value: float):
        """Set a start value, widening bounds when the value lies outside them."""
        lo, hi = par.min, par.max
        par.set(min=min(lo, value), max=max(hi, value))
        par.set(value=value)

    @staticmethod
    def _shift_start_value(par, value: float, lims):
        """Move a chemical shift and its bounds together (keeps the tolerance
        window), without letting the bounds leave the fit window it is in."""
        delta = value - par.value
        lo, hi = par.min + delta, par.max + delta
        for w in lims:
            if min(w) <= value <= max(w):
                lo, hi = max(lo, min(w)), min(hi, max(w))
                break
        par.set(min=min(lo, value), max=max(hi, value))
        par.set(value=value)

    def cancel_fit(self):
        """Request cancellation of a running fit.  (#6 fix)"""
        self._cancel.set()
        self.log.emit("Fit cancellation requested...")

    # ── Step 7: Load from input file ───────────────────────
    def load_input_file(self, path: str):
        """Parse a pyihm input file and populate all state at once.

        FIX #3: Chains fully: parse → set state → load mixture.
        After mixture_loaded, main_window chains to load_components
        using state comp_paths.  Handles mix_txtf.  Stores fit_kws.
        """
        self.log.emit(f"Reading input file: {path}")
        self.reset()   # a new input must not inherit params/regions of the previous one

        def _do_load():
            return read_input_file_resolved(path)

        def _on_done(parsed):
            self._state["bds"] = parsed["bds"]
            self._state["fit_kws"] = parsed["fit_kws"]
            # FIX #4: set Hs and I0 BEFORE load_components so they're preserved
            self._state["Hs"] = parsed["Hs"]
            self._state["I0"] = parsed["I0"]
            self._state["comp_paths"] = parsed["comp_path"]
            self._state["out_root"] = parsed["out_root"]
            self._state["plt_opt"] = parsed["plt_opt"]

            if parsed["lims"]:
                self._state["lims"] = ihm.normalize_windows(parsed["lims"])

            self.log.emit("Input file parsed. Loading mixture spectrum...")

            # mix_txtf: pyihm replaces the processed spectrum with the complex
            # array in this text file (the dataset still supplies acqus)
            txtf = parsed["mix_txtf"] or None
            if txtf and not os.path.isfile(str(txtf)):
                self.error.emit("load_input_file", f"mix_txtf file not found: {txtf}")
                return
            if txtf:
                self.log.emit(f"Using text spectrum: {txtf}")
            self.load_mixture(
                parsed["mix_path"],
                mix_kws=parsed["mix_kws"],
                proc_opt=parsed["proc_opt"],
                mix_txtf=txtf,
            )

        self._run_worker(_do_load, _on_done, "load_input_file")

    # ── Calibration helpers ────────────────────────────────
    def apply_drift(self, comp_idx: int, drift_ppm: float):
        """Set the chemical-shift drift of a single component (absolute, idempotent)."""
        if comp_idx >= len(self._state["comp_peaks"]):
            return
        drifts = self._state["drifts"]
        if len(drifts) < len(self._state["comp_peaks"]):
            drifts.extend([0.0] * (len(self._state["comp_peaks"]) - len(drifts)))
        delta = drift_ppm - drifts[comp_idx]
        drifts[comp_idx] = drift_ppm
        for _, peak in self._state["comp_peaks"][comp_idx].items():
            peak.u += delta
        # Recompute the component spectrum
        spectrum = np.sum(
            [peak() for _, peak in self._state["comp_peaks"][comp_idx].items()],
            axis=0,
        )
        self._state["components"][comp_idx] = spectrum
        self.log.emit(f"Applied drift of {drift_ppm:.4f} ppm to component {comp_idx + 1}")

    def save_calibrated_components(self) -> list[str]:
        """Write each component's current peaks to ``<name>-cal.fvf`` (as pyihm's --cal does).

        Components re-load these calibrated files automatically next time.
        Returns the written paths.
        """
        st = self._state
        if not st["comp_peaks"] or st["ppm"] is None:
            self.error.emit("save_calibration", "Load components first")
            return []
        lims = (float(np.max(st["ppm"])), float(np.min(st["ppm"])))
        written = []
        for path, peaks in zip(st["comp_paths"], st["comp_peaks"]):
            base, ext = os.path.splitext(path)
            if base.endswith("-cal"):
                base = base[:-4]
            target = f"{base}-cal{ext or '.fvf'}"
            try:
                kz.fit.write_vf(target, peaks, lims, 1, header=True)
            except OSError as e:
                self.error.emit("save_calibration", f"Cannot write {target}: {e}")
                continue
            written.append(target)
        if written:
            self.log.emit(f"Calibrated components saved: {', '.join(os.path.basename(w) for w in written)}")
        return written

    @property
    def last_results(self) -> dict | None:
        return self._state["results"]

    @property
    def output_root(self) -> str | None:
        return self._state["out_root"]

    @property
    def figure_options(self) -> dict:
        return ihm.figure_options(self._state["plt_opt"])

    def set_initial_concentration(self, comp_idx: int, value: float):
        """Set the initial guess for a component's concentration."""
        if self._state["I0"] is None:
            self._state["I0"] = [1.0] * len(self._state["components"])
        if comp_idx < len(self._state["I0"]):
            self._state["I0"][comp_idx] = value

    # ── Internal ───────────────────────────────────────────
    def _run_worker(self, fn, on_done, step_name: str, on_cancel=None):
        """Launch a background worker, routing signals.

        FIX #6: uses 'completed'/'failed' to avoid QThread.finished shadow.
        Cleans up worker references properly.
        """
        worker = _Worker(fn)

        def _cleanup():
            if worker in self._workers:
                self._workers.remove(worker)
            worker.deleteLater()

        worker.completed.connect(on_done)
        worker.failed.connect(lambda msg: self.error.emit(step_name, msg))
        if on_cancel is not None:
            worker.cancelled.connect(on_cancel)
        # Use QThread.finished (not our custom signal) for cleanup
        worker.finished.connect(_cleanup)
        # Store reference to prevent GC
        self._workers.append(worker)
        worker.start()
