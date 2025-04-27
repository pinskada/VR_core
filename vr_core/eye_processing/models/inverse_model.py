import numpy as np
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