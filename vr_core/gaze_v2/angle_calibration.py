# ruff: noqa: ERA001

"""Module for calibrating gaze angles."""


import itertools
import queue
import threading
from dataclasses import dataclass
from enum import Enum
from queue import PriorityQueue, Queue
from time import monotonic
from typing import Any

import numpy as np
from numpy.linalg import LinAlgError

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.gaze_v2.gaze_vector_extractor import EyeVectors
from vr_core.ports.interfaces import IGazeService
from vr_core.ports.signals import GazeSignals
from vr_core.utilities.logger_setup import setup_logger

# ---------- Data Classes ----------

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
class ScenePosition:
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
    position: ScenePosition  # type of position


@dataclass
class SceneMarkerWithTOA:
    """A calibration marker from calibration scene with time of arrival (TOA)."""

    scene_marker: SceneMarker
    toa: float  # seconds since calibration start (monotonic)


@dataclass
class EyeVectorsWithTOA:
    """An eyetracker marker with timestamp and eye vectors."""

    timestamp: float  # seconds since calibration start (monotonic)
    eye_vectors: EyeVectors  # eye vectors for both eyes


@dataclass
class CalibrationPair:
    """A pair of distance and corresponding eye vectors with stats."""

    scene_position: ScenePosition  # distance in meters
    eye_vectors: EyeVectors  # eye vectors with stats


# ---------- Calibration ----------

class GazeCalib(BaseService, IGazeService, GazeSignals):
    """Gaze calibration handler for interpupillary distance (IPD) measurements."""

    def __init__(
        self,
        vectors_queue: Queue[EyeVectors],
        comm_router_q: PriorityQueue[Any],
        pq_counter: itertools.count[int],
        gaze_signals: GazeSignals,
        config: Config,
    ) -> None:
        """Initialize the GazeCalib service."""
        super().__init__("GazeCalib")
        self.logger = setup_logger("GazeCalib")

        self.vectors_queue = vectors_queue
        self.comm_router_q = comm_router_q
        self.pq_counter = pq_counter

        self.gaze_calib_s = gaze_signals.gaze_calib_s
        self.calib_finalized_s = gaze_signals.calib_finalized_s
        self.cmd_q: Queue[str] = Queue()

        self.cfg = config
        self._unsubscribe = config.subscribe("gaze", self._on_config_changed)

        self._buf_lock = threading.Lock()

        # --- Lists for calibration data ---
        self.tracker_markers: list[EyeVectorsWithTOA] = []
        self.scene_markers: list[SceneMarkerWithTOA] = []

        self.calib_tracker_markers: list[EyeVectorsWithTOA] = []
        self.calib_scene_markers: list[SceneMarkerWithTOA] = []

        self.pairs: dict[int, CalibrationPair] = {}
        self.debug_pairs: dict[int, list[EyeVectors]] = {}

        self.calib_start_t: float | None = None

        self.online = False
        self.min_distances_for_calib = 3

        # Calibration points for each type
        self.reference_calibrator: CalibrationPair | None = None
        self.distance_calibrator: list[CalibrationPair] | None = None
        self.angle_calibrator: list[CalibrationPair] | None = None

        #self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Start the gaze calibration service."""
        self.online = True
        self._ready.set()

        #self.logger.info("Service started.")


    def _run(self) -> None:
        """Run the gaze calibration service."""
        while not self._stop.is_set():

            self._dequeue_cmds()

            # IPD are pushed to a single queue with two possible consumers -
            # - calibration and main gaze calculation,
            # thus, we need to check if we can dequeue
            if self.gaze_calib_s.is_set():
                self._dequeue_vectors_data()
            else:
                # Sleep briefly to avoid busy waiting
                self._stop.wait(0.1)


    def _on_stop(self) -> None:
        """Stop the gaze calibration service."""
        self.online = False
        self._unsubscribe()

        #self.logger.info("Service stopped.")


# ---------- Public APIs ----------

    def start_of_calibration(self) -> None:
        """Start the gaze calibration.

        Signals to start collecting IPD data for calibration.
        During this phase, the system will gather IPD samples,
        during which markers of the distances and states will be sent
        """
        with self._buf_lock:
            self.tracker_markers.clear()
            self.scene_markers.clear()
        self.calib_finalized_s.clear()
        self.calib_start_t = monotonic()
        self.gaze_calib_s.set()


    def end_of_calibration(self) -> None:
        """Finalize the gaze calibration.

        Called after all distances have been displayed and the model
        can be created upon the measured data.
        """
        self.gaze_calib_s.clear()

        # Retrieve collected data safely
        with self._buf_lock:
            self.calib_tracker_markers, self.tracker_markers = self.tracker_markers, []
            self.calib_scene_markers, self.scene_markers = self.scene_markers, []

        # Send finalize command to the internal queue to decouple processing
        self.cmd_q.put("FINALIZE")


    def set_timestamp(self, dist_point: dict[str, Any]) -> None:
        """Append a scene marker with current timestamp to scene_markers.

        dist_point is a dict coming from Unity / calibration scene.
        It is parsed into a SceneMarker and then wrapped with TOA.
        """
        if self.calib_start_t is None:
            self.logger.error("set_timestamp called but calib_start_t is not set.")
            return

        scene_marker = self._parse_scene_marker(dist_point)
        if scene_marker is None:
            return

        t = monotonic() - self.calib_start_t
        marker_with_toa = SceneMarkerWithTOA(scene_marker=scene_marker, toa=t)

        with self._buf_lock:
            self.scene_markers.append(marker_with_toa)


# ---------- Internals ----------

    def _parse_scene_marker(self, raw: dict[str, Any]) -> SceneMarker | None:  # noqa: PLR0911
        """Parse raw dict from Unity into a SceneMarker.

        Expected keys:
            - "id":         int
            - "state":      "start" | "stop"
            - "type":       "ref" | "dist" | "ang"
            - "position":   "dist": float
                            "hor": float
                            "ver": float
        """
        try:
            marker_id = raw.get("id")
            if marker_id is None:
                self.logger.error("Scene marker parsing failed: 'id' is missing.")
                return None
            marker_id = int(marker_id)

            state_str = raw.get("state")
            if state_str not in {"start", "stop"}:
                self.logger.error("Scene marker parsing failed: invalid 'state': %r.", state_str)
                return None
            state = MarkerState.START if state_str == "start" else MarkerState.STOP

            type_str = raw.get("type")
            match type_str:
                case "ref":
                    mtype = MarkerType.REF
                case "dist":
                    mtype = MarkerType.DIST
                case "ang":
                    mtype = MarkerType.ANG
                case _:
                    self.logger.error("Scene marker parsing failed: invalid 'type': %r.", type_str)
                    return None

            position = raw.get("position")
            if position is None or not isinstance(position, dict):
                self.logger.error("Scene marker parsing failed: invalid 'position': %r.", position)
                return None
            distance = position.get("dist")
            horizontal = position.get("hor")
            vertical = position.get("ver")

            if distance is None or horizontal is None or vertical is None:
                self.logger.error(
                    "Scene marker parsing failed: incomplete 'position': %r.", position,
                )
                return None
            pos = ScenePosition(
                distance=distance,
                horizontal=horizontal,
                vertical=vertical,
            )

        except (TypeError, ValueError) as e:
            self.logger.error("Scene marker parsing failed: %s", e)  # noqa: TRY400
            return None

        return SceneMarker(
            id=marker_id,
            state=state,
            type=mtype,
            position=pos,
        )


    def _dequeue_cmds(self) -> None:
        """Dequeue commands from the command queue."""
        try:
            cmd = self.cmd_q.get(timeout=0.001)
            match cmd:
                case "FINALIZE":
                    try:
                        self._finalize_calibration()
                    except (ValueError, TypeError, LinAlgError, OverflowError):
                        # Expected/known failure modes in calibration & fitting
                        self.logger.exception("Finalize failed (expected type)")
                    except Exception:  # pylint: disable=broad-except
                        # Truly unexpected — still don't crash the service thread
                        self.logger.exception("Finalize failed (unexpected error)")
                case _:
                    self.logger.error("Unknown command: %s", cmd)
        except queue.Empty:
            pass


    def _dequeue_vectors_data(self) -> None:
        """Dequeue vectors data from the vectors queue."""
        try:
            vector_data = self.vectors_queue.get(timeout=self.cfg.gaze2.vector_queue_timeout)
            self._append_vectors(vector_data)
        except queue.Empty:
            pass


    def _append_vectors(self, vector_data: EyeVectors) -> None:
        """Append the tracker eye vectors to the tracker_markers list with a timestamp."""
        if self.calib_start_t is None:
            self.logger.error("calib_start_t is not set.")
            return
        t = monotonic() - self.calib_start_t
        with self._buf_lock:
            self.tracker_markers.append(EyeTrackerMarker(t, vector_data))


    def _validate_scene_markers(self) -> bool:  # noqa: C901, PLR0911, PLR0912
        """Check and validate the scene markers.

        Ensures that markers:
            - are in chronological order,
            - form non-overlapping START/STOP intervals,
            - have matching IDs (and matching type/position) for each START/STOP pair.

        For distance markers (MarkerType.DIST) it also checks that there are at
        least 'self.min_distances_for_calib' distinct distances.

        Returns:
            bool: True if validation is successful, False otherwise.

        """
        if not self.calib_scene_markers:
            self.logger.error("No scene markers provided.")
            return False

        # Sort by time-of-arrival to have a deterministic pass
        markers = sorted(self.calib_scene_markers, key=lambda m: m.toa)

        validated: list[SceneMarkerWithTOA] = []
        open_start: SceneMarkerWithTOA | None = None
        distinct_distances: set[float] = set()

        for m_toa in markers:
            sm = m_toa.scene_marker

            if sm.state == MarkerState.START:
                # Must not start a new interval while one is open
                if open_start is not None:
                    self.logger.error(
                        "Invalid markers: START (id=%d) at t=%.6f before previous STOP "
                        "(id=%d at t=%.6f).",
                        sm.id, m_toa.toa,
                        open_start.scene_marker.id, open_start.toa,
                    )
                    return False

                open_start = m_toa
                validated.append(m_toa)

            else:  # STOP
                if open_start is None:
                    self.logger.error(
                        "Invalid markers: STOP (id=%d) at t=%.6f without a matching START.",
                        sm.id, m_toa.toa,
                    )
                    return False

                sm_start = open_start.scene_marker

                # ID must match the open interval
                if sm.id != sm_start.id:
                    self.logger.error(
                        "Invalid markers: STOP (id=%d) does not match START (id=%d).",
                        sm.id, sm_start.id,
                    )
                    return False

                # Type and position should also match for sanity
                if sm.type != sm_start.type or sm.position != sm_start.position:
                    self.logger.error(
                        "Invalid markers: START/STOP mismatch for id=%d "
                        "(type/position differ).",
                        sm_start.id,
                    )
                    return False

                # STOP must be strictly after START
                if m_toa.toa <= open_start.toa:
                    self.logger.error(
                        "Invalid markers: STOP (id=%d, t=%.6f) not after START (t=%.6f).",
                        sm.id, m_toa.toa, open_start.toa,
                    )
                    return False

                # Pair is valid: record STOP and close interval
                validated.append(m_toa)

                if sm_start.type == MarkerType.DIST:
                    distinct_distances.add(sm_start.position.distance)

                open_start = None

        # No unclosed interval remaining
        if open_start is not None:
            sm = open_start.scene_marker
            self.logger.error(
                "Invalid markers: last START (id=%d) at t=%.6f (distance %.6f) "
                "has no matching STOP.",
                sm.id,
                open_start.toa,
                sm.position.distance,
            )
            return False

        # If we have any distance markers, require at least N distinct distances
        if distinct_distances and len(distinct_distances) < self.min_distances_for_calib:
            self.logger.error(
                "Not enough distinct distances for calibration: got %d, need at least %d.",
                len(distinct_distances), self.min_distances_for_calib,
            )
            return False

        # Sanity check that validated list is even-length and alternates START/STOP
        if len(validated) % 2 != 0:
            self.logger.error("Internal error: validated marker list length is not even.")
            return False

        for i in range(0, len(validated), 2):
            if (
                validated[i].scene_marker.state != MarkerState.START
                or validated[i + 1].scene_marker.state != MarkerState.STOP
            ):
                self.logger.error(
                    "Internal error: validated markers do not alternate START/STOP.",
                )
                return False

        self.logger.info(
            "Validated %d intervals across %d distinct distances.",
            len(validated) // 2,
            len(distinct_distances),
        )

        # Overwrite with the validated, ordered list
        self.calib_scene_markers = validated
        return True

# adam smrdi, oprav tohle pls
    def _extract_marker_pairs(self) -> None:
        """Extract vector marker intervals from self.calib_tracker_markers and processes them.

        Creates pairs of EyeVectorsWithStats - SceneMarker for each scene marker.
        Uses each interval's collected tracker markers via self._process_interval().
        """
        # TODO: Requires refactor to extract tracker_vectors.

        # 1) Match IPD samples with distance markers
        # 2) Compute a single processed IPD for each interval using self._process_interval()
        # 3) Return a dictionary of distance-IPD pairs, where ipd is tuple of (mean, std, n_samples)

        if not self.calib_tracker_markers or not self.calib_scene_markers:
            self.logger.error("Cannot extract pairs: empty samples or markers.")
            return

        # Ensure time order
        samples = sorted(self.calib_tracker_markers, key=lambda s: s.timestamp)
        markers = self.calib_scene_markers

        self.pairs = {}
        self.debug_pairs = {}

        s_idx = 0
        s_len = len(samples)

        for i in range(0, len(markers), 2):
            start_m = markers[i]
            stop_m  = markers[i + 1]
            distance = stop_m.distance  # same as start_m.distance by validation

            # Advance to first sample inside the interval
            while s_idx < s_len and samples[s_idx].timestamp < start_m.timestamp:
                s_idx += 1

            # Collect samples within [start, stop]
            interval: list[EyeTrackerMarker] = []
            j = s_idx
            while j < s_len and samples[j].timestamp <= stop_m.timestamp:
                interval.append(samples[j])
                j += 1

            # Move head index forward for next interval (monotonic markers)
            s_idx = j

            if not interval:
                self.logger.warning(
                    "No IPD samples found in interval [%.4f, %.4f] for distance %.3f.",
                    start_m.timestamp, stop_m.timestamp, distance,
                )
                continue

            processed = self._process_interval(interval, distance)
            if processed is None:
                self.logger.warning(
                    "Interval for distance %.3f rejected by processing; skipping.", distance,
                )
                continue

            mean_val, std_val, n_used = processed

            self.pairs[distance] = (float(mean_val), float(std_val), int(n_used))
            self.debug_pairs[distance] = interval

            self.logger.debug(
                "Distance %.3f -> mean=%.6f, std=%.6f, n=%d (interval [%.4f, %.4f]).",
                distance, self.pairs[distance][0], self.pairs[distance][1], self.pairs[distance][2],
                start_m.timestamp, stop_m.timestamp,
            )

        if len(self.pairs) < self.min_distances_for_calib:
            self.logger.error(
                "Only %d distances produced valid data after processing (need ≥3).",
                len(self.pairs),
            )
            return


    def _process_interval(
        self,
        tracker_marker_list: list[EyeVectors],
        scene_marker: SceneMarker,
    ) -> tuple[float, float, int] | None:
        """Process a single scene interval's collected tracker markers.

        Returns a list of x and y means, x and y stddevs, and number of samples used for each eye.

        
        Args:
            tracker_marker_list: List of EyeVectors collected during the interval.
            scene_marker: The scene marker defining the interval.
        
        Returns:

        """
        # TODO: Requires refactor to process tracker_vectors.
        n_total = len(ipd_interval)
        if n_total < self.cfg.gaze2.vector_min_samples:
            self.logger.warning("Not enough samples collected for distance. "
                "Collected %d, need at least %d.", n_total, self.cfg.gaze2.vector_min_samples)
            return None

        arr = np.array([s.ipd_value for s in ipd_interval], dtype=float)

        # Remove NaN/Inf samples
        finite_mask = np.isfinite(arr)
        if not finite_mask.all():
            n_removed = np.count_nonzero(~finite_mask)
            arr = arr[finite_mask]
            self.logger.debug(
                "Removed %d non-finite IPD samples (NaN/Inf) for distance %.2f.",
                n_removed, distance,
            )

        # If all values are invalid, reject interval
        if arr.size == 0:
            self.logger.warning("All IPD samples invalid (NaN/Inf) for distance %.2f.", distance)
            return None

        # Edge crop
        n = len(arr)
        crop_n = int(n * self.cfg.gaze2.buffer_crop_factor)
        if crop_n * 2 >= n:
            self.logger.warning(
                "Interval for distance %.2f invalid after cropping (n=%d, crop_n=%d).",
                distance, n, crop_n,
            )
            return None
        arr = arr[crop_n:-crop_n]

        if arr.size < self.cfg.gaze2.vector_min_samples:
            self.logger.warning(
                "Not enough samples after cropping for distance %.2f: have %d, need at least %d.",
                distance, arr.size, self.cfg.gaze2.vector_min_samples,
            )
            return None

        # Compute stats
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))

        # --- Validate sample quality ---
        if std_val > self.cfg.gaze2.std_threshold:
            self.logger.warning("High standard deviation detected (%f).", std_val)
            return None

        return mean_val, std_val, len(arr)


    def _sort_scene_markers(self) -> None:
        """Sort scene markers by their marker type.

        Iterates through self.calib_scene_markers and sorts them into self.reference_calibrator,
        self.distance_calibrator, and self.angle_calibrator based on their marker type.
        """


    def _fit_model(self) -> bool:
        """Fit the model to the eye data."""
        # TODO: Implement model fitting logic here.
        return True


    def compensate_for_impairment(self) -> None:
        """Compensate for users visual impairment."""
        # TODO: Optionaly implement or discard this method.


    def _finalize_calibration(self) -> None:
        """Finalize the calibration by processing.

        Averages and processes IPDs in each distance interval,
        creating distance-IPD pairs and fitting the model.
        """
        # Checks and validates for enough distances to fit the model
        self._validate_scene_markers()
        if not self.calib_scene_markers:
            self.logger.error("Calibration finalization aborted due to invalid distance markers.")
            return

        # Extracts IPD intervals by comparing timestamps and creates distance-IPD dictionary
        self._extract_ipd_dist_pairs()

        # Fit the model using the collected dict pairs
        if not self._fit_model():
            self.logger.error("Calibration finalization aborted due to model fitting failure.")
            return

        # Signal to GazeControl that calibration is finalized
        self.calib_finalized_s.set()


    # pylint: disable=unused-argument
    def _on_config_changed(self, path: str, old_val: Any, new_val: Any) -> None:  # noqa: ANN401, ARG002
        """Handle configuration changes."""
        if path in {
            "gaze.diop_impairment",
            "gaze.compensation_factor",
            "gaze.max_diop_impairment",
            "gaze.max_shift_factor",
        } and self.cfg.gaze2.model_params is not None:
            # Re-apply compensation if impairment setting changes
            self.compensate_for_impairment()
