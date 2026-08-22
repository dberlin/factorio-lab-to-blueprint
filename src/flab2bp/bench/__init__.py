"""The bake-off: run every layout strategy over a corpus and measure them.

Both strategies get the same ``BuildSpec``, the same budget, and the same seed,
and neither is asked how it did -- the harness measures each ``Placement``
itself.  A strategy reporting its own numbers would be marking its own homework.
"""

from flab2bp.bench.corpus import URL_CORPUS, CorpusEntry, Tier, entries_for, entry
from flab2bp.bench.crossvalidate import CrossCheck, bun_available, crossvalidate, viewer_path
from flab2bp.bench.metrics import measure
from flab2bp.bench.regression import (
    AREA_TOLERANCE,
    Regression,
    RegressionResult,
    check_against_baseline,
    write_baseline,
)
from flab2bp.bench.report import MatrixReport, matrix_report, render_markdown, write_results
from flab2bp.bench.runner import available_strategies, run_corpus, specs_for
from flab2bp.bench.scoring import DENSITY_DEADBAND, Verdict, compare, geometric_mean
from flab2bp.bench.types import CellResult, Metrics

__all__ = [
    "AREA_TOLERANCE",
    "DENSITY_DEADBAND",
    "CellResult",
    "CorpusEntry",
    "CrossCheck",
    "MatrixReport",
    "Metrics",
    "Regression",
    "RegressionResult",
    "Tier",
    "URL_CORPUS",
    "Verdict",
    "available_strategies",
    "bun_available",
    "check_against_baseline",
    "compare",
    "crossvalidate",
    "entries_for",
    "entry",
    "geometric_mean",
    "matrix_report",
    "measure",
    "render_markdown",
    "run_corpus",
    "specs_for",
    "viewer_path",
    "write_baseline",
    "write_results",
]
