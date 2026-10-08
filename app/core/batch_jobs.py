"""Batch job description, discovery and the worker-process entry point.

Qt-free and cheap to import: worker processes unpickle :func:`run_batch_job`
from here, and the heavy pyihm/klassez stack is only imported when a job runs.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial

BLAS_THREAD_VARS = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS",
)
THREAD_ENV = {name: "1" for name in BLAS_THREAD_VARS}

MIXTURE_FILE_EXTS = (".jdf",)
OUTPUT_DIR_SUFFIXES = ("-DATA", "-FIGURES")

_threadpool_limiter = None


@contextmanager
def worker_environ():
    """Single-threaded BLAS environment for the lifetime of a worker pool.

    Spawned workers inherit it before numpy loads its BLAS, which is the only
    point where these variables take effect.
    """
    saved = {name: os.environ.get(name) for name in THREAD_ENV}
    os.environ.update(THREAD_ENV)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def init_worker():
    """Pool initializer: one BLAS thread and a headless matplotlib per worker.

    Covers forked workers (BLAS already loaded, so the environment is too late)
    through ``threadpoolctl`` when it is installed.
    """
    global _threadpool_limiter
    os.environ.update(THREAD_ENV)
    os.environ.setdefault("MPLBACKEND", "Agg")
    try:
        from threadpoolctl import threadpool_limits
    except ImportError:
        return
    _threadpool_limiter = threadpool_limits(limits=1)


@dataclass(frozen=True)
class BatchJob:
    """One fit: an input file, optionally applied to a different mixture."""
    inp_path: str
    mix_path: str | None = None
    out_root: str | None = None
    label: str = ""

    @property
    def name(self) -> str:
        if self.label:
            return self.label
        return os.path.basename(os.path.normpath(self.mix_path or self.inp_path))


def _natural_key(text: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text.lower())]


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(os.path.normpath(path)))[0]


def _unique_names(names: list[str]) -> list[str]:
    """Suffix repeated names (case-insensitively) so every output root differs."""
    seen: dict[str, int] = {}
    out = []
    for name in names:
        key = name.lower()
        seen[key] = seen.get(key, 0) + 1
        out.append(name if seen[key] == 1 else f"{name}_{seen[key]}")
    return out


def discover_mixtures(folder: str, exclude: tuple[str, ...] = ()) -> list[str]:
    """Mixture spectra directly inside ``folder``, in natural order.

    Sub-directories (Bruker/Varian datasets) and single-file formats count;
    hidden entries, pyihm output folders and anything in ``exclude`` do not.
    """
    skip = {os.path.normcase(os.path.abspath(p)) for p in exclude}
    found = []
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        if name.startswith(".") or os.path.normcase(os.path.abspath(full)) in skip:
            continue
        if os.path.isdir(full):
            if name.endswith(OUTPUT_DIR_SUFFIXES):
                continue
        elif os.path.splitext(name)[1].lower() not in MIXTURE_FILE_EXTS:
            continue
        found.append(os.path.abspath(full))
    return sorted(found, key=lambda p: _natural_key(os.path.basename(p)))


def build_template_jobs(template_inp: str, mixtures: list[str], out_dir: str) -> list[BatchJob]:
    """Mode B: one template input applied to every mixture."""
    names = _unique_names([_stem(m) for m in mixtures])
    return [
        BatchJob(os.path.abspath(template_inp), os.path.abspath(m),
                 os.path.join(out_dir, name), label=os.path.basename(os.path.normpath(m)))
        for m, name in zip(mixtures, names)
    ]


def build_input_file_jobs(inp_paths: list[str], out_dir: str) -> list[BatchJob]:
    """Mode A: every input file is a job with its own mixture and settings."""
    names = _unique_names([_stem(p) for p in inp_paths])
    return [
        BatchJob(os.path.abspath(p), None, os.path.join(out_dir, name),
                 label=os.path.basename(p))
        for p, name in zip(inp_paths, names)
    ]


def run_batch_job(job: BatchJob, *, method: str = "tight", align: bool = True) -> dict:
    """Worker entry point: run one job and return its small summary dict."""
    from app.core.ihm_runner import run_ihm

    overrides = {"mix_path": job.mix_path} if job.mix_path else None
    try:
        summary = run_ihm(
            job.inp_path, method=method, align=align, out_root=job.out_root,
            overrides=overrides, save=True, use_calibrated=True,
        )
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {e}") from None
    summary["label"] = job.name
    return summary


def batch_fit_fn(method: str = "tight", align: bool = True):
    """Picklable ``fit_fn`` for :class:`BatchProcessor`."""
    return partial(run_batch_job, method=method, align=align)
