"""Types for gaze vector extraction and calibration."""

from dataclasses import dataclass
from enum import Enum

# ---------- vector extractor types ----------

@dataclass
class EyeVector:
    """A 2D CR->pupil vector sample in pixels."""

    dx: float  # pixels
    dy: float  # pixels


@dataclass
class EyeVectors:
    """Per-eye 2D vectors (dx, dy) in cropped-eye pixel coordinates."""

    left_eye_vector: EyeVector
    right_eye_vector: EyeVector


# ------------ calibrate data types ------------

@dataclass
class ReferenceParams:
    """Near-infinite reference vectors for both eyes."""
    left_ref: tuple[float, float]   # (dx0_L, dy0_L)
    right_ref: tuple[float, float]  # (dx0_R, dy0_R)


@dataclass
class AngleFitFunction:
    """Parameters for angle fitting function."""
    coeffs: list[float]  # highest degree first


@dataclass
class AngleParamsPerEye:
    """Angle conversion constants for one eye."""
    fx: AngleFitFunction  # horizontal pixel-to-angle mapping funtion
    fy: AngleFitFunction  # vertical pixel-to-angle mapping funtion


@dataclass
class AngleParams:
    """Angle conversion constants for both eyes."""
    left: AngleParamsPerEye
    right: AngleParamsPerEye


@dataclass
class DistanceParams:
    """Parameters for distance adjustment function."""
    a: float  # scale
    b: float  # bias


@dataclass
class CalibratedData:
    """Calibrated data containing reference, angle, and distance parameters."""
    reference: ReferenceParams
    angle: AngleParams
    distance: DistanceParams

# ----------------- gaze calibration types -----------------

class MarkerState(Enum):
    """Marker state for distance calibration."""

    START = "start"
    STOP = "stop"


class MarkerType(Enum):
    """Marker type for calibration type."""

    REF = "reference"  # Use for calibrating eye position reference
    DIST = "distance"  # Use for calibrating distance
    ANG = "angle"  # Use for calibrating angles


@dataclass
class TargetPosition:
    """Target position in the scene of the calibration marker."""

    distance: float  # distance in meters for DIST type
    horizontal: float  # horizontal angle in degrees for ANG type
    vertical: float  # vertical angle in degrees for ANG type


@dataclass
class SceneMarker:
    """A calibration marker from calibration scene."""

    id: int  # Unique identifier for every marker (same ID for start/stop)
    state: MarkerState  # start or stop
    type: MarkerType  # reference, distance, or angles
    target_position: TargetPosition  # type of position


@dataclass
class SceneMarkerWithTOA:
    """A calibration marker from calibration scene with time of arrival (TOA)."""

    scene_marker: SceneMarker
    toa: float  # seconds since calibration start (monotonic)


@dataclass
class EyeVectorsWithTOA:
    """An eyetracker marker with toa and eye vectors."""

    toa: float  # seconds since calibration start (monotonic)
    eye_vectors: EyeVectors  # eye vectors for both eyes


@dataclass
class CalibStats:
    """Statistics for each calibration pair."""
    n_samples: int                 # total samples after filtering/cropping
    std_left: tuple[float, float]  # (std_dx, std_dy)
    std_right: tuple[float, float] # (std_dx, std_dy)


@dataclass
class CalibrationPair:
    """A pair of distance and corresponding eye vectors with stats."""

    target_position: TargetPosition  # distance in meters
    eye_vectors: EyeVectors  # eye vectors
    marker_id: int
    calib_stats: CalibStats  # statistics


@dataclass
class Calibrator:
    """Holds calibration pairs for reference, distance, and angle calibrations."""

    ref_calibrator: CalibrationPair  # reference target calibration pair
    dist_calibrators: list[CalibrationPair]  # distance target calibration pairs
    angle_calibrators: list[CalibrationPair]  # angle target calibration pairs
