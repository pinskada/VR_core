"""Inverse model for gaze estimation."""

from typing import Tuple
import math

import numpy as np


def fit(distances, ipds) -> Tuple[float, float]:
    """
    Fit the model: IPD ≈ a / distance + b
    """
    d = np.asarray(distances, dtype=float)
    y = np.asarray(ipds, dtype=float)

    if d.shape != y.shape or d.ndim != 1:
        raise ValueError("distances and ipds must be 1D arrays of the same length")
    if d.size < 2:
        raise ValueError("Need at least 2 points to fit")

    # Keep only finite, strictly positive distances and finite IPDs
    mask = np.isfinite(d) & np.isfinite(y) & (d > 0.0)
    d = d[mask]
    y = y[mask]
    if d.size < 2:
        raise ValueError("Not enough valid points after filtering (need ≥ 2)")

    x = 1.0 / d  # linearize

    # Linear fit: y ≈ a*x + b
    # r[0] is slope (a), r[1] is intercept (b)
    a, b = np.polyfit(x, y, deg=1)

    return float(a), float(b)


def predict(ipd, model_params):
    """
    Invert the model to predict distance from IPD.
    model_params should be (a, b).
    """
    a, b = model_params
    return a / (ipd - b)


def safe_predict(ipd, model_params, eps=1e-6):
    """
    Robust version of predict() with singularity guard and sanity checks.
    - Avoids division by zero when ipd ~= b by nudging denominator by sign*eps.
    - Raises ValueError on non-finite input or degenerate parameters.
    """

    if not isinstance(model_params, (list, tuple)) or len(model_params) != 2:
        raise ValueError("model_params must be (a, b)")

    a, b = float(model_params[0]), float(model_params[1])

    if not (math.isfinite(a) and math.isfinite(b)):
        raise ValueError("model_params contain non-finite values")

    if not math.isfinite(ipd):
        raise ValueError("IPD is not finite")

    denom = ipd - b
    if denom < eps:
        denom = eps

    d = a / denom
    if not math.isfinite(d):
        raise ValueError("Predicted distance is not finite")

    return d
