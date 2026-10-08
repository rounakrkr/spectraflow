"""Core package. Exports load lazily so Qt-free modules (``ihm_runner``,
``batch_jobs``, ``exporter``) can be imported in worker processes without
pulling in PySide6."""

import importlib

_EXPORTS = {
    "Pipeline": "pipeline",
    "FitWorker": "workers",
    "FitCancelled": "workers",
    "SpectrumLoadWorker": "workers",
    "BatchProcessor": "batch_processor",
    "AnalysisEngine": "engine",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value
