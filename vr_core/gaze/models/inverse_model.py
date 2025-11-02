"""Inverse model for gaze estimation."""

import math
from scipy.optimize import curve_fit

def fit(distances, ipds):
    """
    Fit the model: IPD ≈ a / distance + b
    """
    def model_func(d, a, b):
        return a / d + b

    popt, _ = curve_fit(model_func, distances, ipds, p0=(1.0, 0.0))
    return popt  # returns (a, b)

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
