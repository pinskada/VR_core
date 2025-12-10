# ruff: noqa: N806, ERA001

"""Calibrate data in a three step process."""

import numpy as np

import vr_core.gaze_v2.calibration_types as ct


def calibrate_data(calibrator: ct.Calibrator) -> ct.CalibratedData:
    """Calibrate data in a three step process.

    Args:
        calibrator: The calibrator object containing calibration data.

    Returns:
        Calibrated data object:
            Reference target vectors for both eyes.
            Vertical and horizontal angles conversion constants for both eyes.
            Distance adjustment function constants.

    """
    ref_params = calibrate_reference(calibrator.ref_calibrator)
    angle_params = calibrate_angle(calibrator.angle_calibrators, ref_params)
    dist_params = calibrate_distance(
        calibrator.dist_calibrators,
        ref_params,
        angle_params,
    )

    return ct.CalibratedData(
        reference=ref_params,
        angle=angle_params,
        distance=dist_params,
    )


def calibrate_reference(ref_calibrator: ct.CalibrationPair) -> ct.ReferenceParams:
    """Create reference target vectors.

    Args:
        ref_calibrator: The reference calibrator object containing reference calibration data.

    Returns:
        Reference target vectors for both eyes.

    """
    dx0_L = ref_calibrator.eye_vectors.left_eye_vector.dx
    dy0_L = ref_calibrator.eye_vectors.left_eye_vector.dy
    dx0_R = ref_calibrator.eye_vectors.right_eye_vector.dx
    dy0_R = ref_calibrator.eye_vectors.right_eye_vector.dy

    return ct.ReferenceParams(
        left_ref=(dx0_L, dy0_L),
        right_ref=(dx0_R, dy0_R),
    )


def calibrate_angle(
    angle_calibrator: list[ct.CalibrationPair],
    reference_params: ct.ReferenceParams,
) -> ct.AngleParams:
    """Calibrate angle conversion.

    Args:
        angle_calibrator: List of calibration pairs for angle calibration.
        reference_params: Reference parameters containing reference vectors for both eyes.

    Returns:
        Angle conversion constants for both eyes.

    Fits pixel-to-angle mappings for each eye and axis using angle calibration targets.
    The fitted functions map (dx - dx0) -> alpha_x and (dy - dy0) -> alpha_y, where
    (dx0, dy0) comes from the reference calibration.

    """
    dx0_L, dy0_L = reference_params.left_ref
    dx0_R, dy0_R = reference_params.right_ref

    # Arrays for regression data
    left_dx, left_alpha_x, left_wx = [], [], []
    right_dx, right_alpha_x, right_wx = [], [], []

    left_dy, left_alpha_y, left_wy = [], [], []
    right_dy, right_alpha_y, right_wy = [], [], []

    eps = 1e-3  # tolerance to decide "purely horizontal" / "purely vertical"
    eps_std = 1e-6

    for cp in angle_calibrator:
        tp = cp.target_position
        ev = cp.eye_vectors
        stats = cp.calib_stats

        # Offsets from reference
        dLx = ev.left_eye_vector.dx  - dx0_L
        dLy = ev.left_eye_vector.dy  - dy0_L
        dRx = ev.right_eye_vector.dx - dx0_R
        dRy = ev.right_eye_vector.dy - dy0_R

        # Horizontal calibration points: vertical angle ~ 0
        if abs(tp.vertical) < eps:
            left_dx.append(dLx)
            left_alpha_x.append(tp.horizontal)

            right_dx.append(dRx)
            right_alpha_x.append(tp.horizontal)

            # Weights from per-axis std + sample count
            std_Lx = stats.std_left[0]
            std_Rx = stats.std_right[0]

            wL = stats.n_samples / max(std_Lx, eps_std)
            wR = stats.n_samples / max(std_Rx, eps_std)

            left_wx.append(wL)
            right_wx.append(wR)

        # Vertical calibration points: horizontal angle ~ 0
        if abs(tp.horizontal) < eps:
            left_dy.append(dLy)
            left_alpha_y.append(tp.vertical)

            right_dy.append(dRy)
            right_alpha_y.append(tp.vertical)

            std_Ly = stats.std_left[1]
            std_Ry = stats.std_right[1]

            wL = stats.n_samples / max(std_Ly, eps_std)
            wR = stats.n_samples / max(std_Ry, eps_std)

            left_wy.append(wL)
            right_wy.append(wR)

    # Fit polynomials for each eye & axis (degree can be tuned)
    fx_left = _fit_angle_poly(left_dx, left_alpha_x, left_wx,  "left horizontal", degree=1)
    fy_left = _fit_angle_poly(left_dy, left_alpha_y, left_wy,  "left vertical", degree=1)
    fx_right = _fit_angle_poly(right_dx, right_alpha_x, right_wx, "right horizontal", degree=1)
    fy_right = _fit_angle_poly(right_dy, right_alpha_y, right_wy, "right vertical", degree=1)

    left_params = ct.AngleParamsPerEye(fx=fx_left, fy=fy_left)
    right_params = ct.AngleParamsPerEye(fx=fx_right, fy=fy_right)

    return ct.AngleParams(left=left_params, right=right_params)


def calibrate_distance(
    distance_calibrator: list[ct.CalibrationPair],
    ref_params: ct.ReferenceParams,
    angle_params: ct.AngleParams,
) -> ct.DistanceParams:
    """Calibrate distance adjustment.

    Fits a model of the form:

        distance ≈ a / theta + b

    where theta is the binocular vergence angle in radians (derived from the
    horizontal angles of both eyes).

    Args:
        distance_calibrator: The distance calibrator object containing distance calibration data.
        ref_params: Reference parameters containing reference vectors for both eyes.
        angle_params: Angle conversion constants for both eyes.

    Returns:
        DistanceParams: Distance adjustment function constants.

    """
    dx0_L, _ = ref_params.left_ref
    dx0_R, _ = ref_params.right_ref

    z_vals: list[float] = []  # 1 / vergence_rad
    d_vals: list[float] = []  # ground-truth distances [m]
    w_vals: list[float] = []  # weights

    eps_theta = 1e-6
    eps_std = 1e-6

    for cp in distance_calibrator:
        tp = cp.target_position
        ev = cp.eye_vectors
        stats = cp.calib_stats

        # Offsets from reference
        dLx = ev.left_eye_vector.dx  - dx0_L
        dRx = ev.right_eye_vector.dx - dx0_R

        # Convert pixel offsets to horizontal angles (deg)
        alpha_L = _eval_angle_poly(angle_params.left.fx, dLx)
        alpha_R = _eval_angle_poly(angle_params.right.fx, dRx)

        # Vergence in radians (magnitude)
        vergence_deg = abs(alpha_L - alpha_R)
        vergence_rad = float(np.deg2rad(vergence_deg))

        if vergence_rad < eps_theta:
            # This would correspond to "infinite" distance, which should be
            # handled by the reference calibration, not distance calibration.
            # Skip and warn.
            # (You might want to log here instead of silently skipping.)
            continue

        z = 1.0 / vergence_rad
        d = tp.distance

        # Combined horizontal std from both eyes
        std_Lx = stats.std_left[0]
        std_Rx = stats.std_right[0]
        std_combined = 0.5 * (std_Lx + std_Rx)

        w = stats.n_samples / max(std_combined, eps_std)

        z_vals.append(z)
        d_vals.append(d)
        w_vals.append(w)

    min_distance_points = 2
    if len(z_vals) < min_distance_points:
        error = ("Not enough valid distance calibration points: got %s, "
            "need at least 2.", len(z_vals))
        raise ValueError(error)

    z_arr = np.asarray(z_vals, dtype=float)
    d_arr = np.asarray(d_vals, dtype=float)
    w_arr = np.asarray(w_vals, dtype=float)

    # Fit d ≈ a * z + b  (weighted)
    coeffs = np.polyfit(z_arr, d_arr, 1, w=w_arr)  # coeffs[0] = a, coeffs[1] = b
    a, b = float(coeffs[0]), float(coeffs[1])

    return ct.DistanceParams(a=a, b=b)


def _eval_angle_poly(f: ct.AngleFitFunction, x: float) -> float:
    """Evaluate an angle polynomial at x."""
    return float(np.polyval(f.coeffs, x))


def _fit_angle_poly(
    x_vals: list[float],
    y_vals: list[float],
    w_vals: list[float],
    label: str,
    degree: int = 2,
) -> ct.AngleFitFunction:
    """Fit alpha ≈ poly(dx) for a single eye/axis."""
    if len(x_vals) < degree + 1:
        error = ("Not enough points to fit %s: have %s, "
            "need at least %s.", label, len(x_vals), degree + 1)
        raise ValueError(error)

    if len(x_vals) != len(y_vals) or len(x_vals) != len(w_vals):
        error = ("Length mismatch for %s.", label, len(x_vals), len(y_vals))
        raise ValueError(error)

    x = np.asarray(x_vals, dtype=float)
    y = np.asarray(y_vals, dtype=float)
    w = np.asarray(w_vals, dtype=float)

    # Weighted least-squares polynomial fit
    coeffs = np.polyfit(x, y, degree, w=w)
    coeffs_list = [float(c) for c in coeffs]

    return ct.AngleFitFunction(coeffs=coeffs_list)
