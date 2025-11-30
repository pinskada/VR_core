"""Datatypes for eye_tracker module."""

from dataclasses import dataclass


@dataclass
class CrData:
    """Dataclass for corneal reflection data."""

    center: tuple[float, float]
    radius: float
    is_filled: bool


@dataclass
class PupilData:
    """Dataclass for pupil data."""

    center: tuple[float, float]
    radius: float


@dataclass
class OneSideTrackerData:
    """Output data from one side of the eye tracker."""
    pupil: PupilData
    crs: list[CrData]


@dataclass
class TwoSideTrackerData:
    """Output data from both sides of the eye tracker."""
    left_eye_data: OneSideTrackerData
    right_eye_data: OneSideTrackerData


@dataclass
class DTCandidate:
    """Dataclass for distance transform candidate data."""

    center: tuple[float, float]
    radius_estimate: float
    area: float
    circularity: float
    score: float
