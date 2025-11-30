"""Module for computing eye vectors from tracker data."""

from dataclasses import dataclass

# ---------- Data Classes ----------

@dataclass
class VectorSample:
    """A 2D CR->pupil vector sample in pixels."""

    dx: float  # pixels
    dy: float  # pixels


@dataclass
class EyeVectors:
    """Per-eye 2D vectors (dx, dy) in cropped-eye pixel coordinates."""

    left_eye_vector: VectorSample
    right_eye_vector: VectorSample

# ---------- Gaze Vector Extractor ----------
# TBD
