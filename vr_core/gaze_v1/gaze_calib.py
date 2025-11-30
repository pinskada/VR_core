# ruff: noqa: ERA001

"""Gaze model calibration module."""

import itertools
import math
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
from vr_core.gaze_v1.models import inverse_model
from vr_core.ports.interfaces import IGazeService
from vr_core.ports.signals import GazeSignals
from vr_core.utilities.logger_setup import setup_logger


class MarkerState(Enum):
    """Marker state for distance calibration."""

    START = "start"
    STOP = "stop"

@dataclass
class IPDSample:
    """A single IPD measurement with a timestamp."""

    timestamp: float  # seconds since calibration start (monotonic)
    ipd_value: float

@dataclass
class DistanceMarker:
    """A calibration marker indicating start or stop at a specific distance."""

    timestamp: float
    state: MarkerState
    distance: float


class GazeCalib(BaseService, IGazeService, GazeSignals):
    """Gaze calibration handler for interpupillary distance (IPD) measurements."""

    def __init__(
        self,
        ipd_q: Queue,
        comm_router_q: PriorityQueue,
        pq_counter: itertools.count,
        gaze_signals: GazeSignals,
        config: Config,
    ) -> None:
        """Initialize the GazeCalib service."""
        super().__init__("GazeCalib")
        self.logger = setup_logger("GazeCalib")

        self.ipd_q = ipd_q
        self.comm_router_q = comm_router_q
        self.pq_counter = pq_counter

        self.gaze_calib_s = gaze_signals.gaze_calib_s
        self.calib_finalized_s = gaze_signals.calib_finalized_s
        self.cmd_q: Queue = Queue()

        self.cfg = config
        self._unsubscribe = config.subscribe("gaze", self._on_config_changed)

        self._buf_lock = threading.Lock()

        # --- Lists for calibration data ---
        self.ipd_samples: list[IPDSample] = []
        self.dist_markers: list[DistanceMarker] = []

        self.calib_start_t: float | None = None

        self.online = False
        self.min_distances_for_calib = 3

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
                self._dequeue_ipd_data()
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
            self.ipd_samples.clear()
            self.dist_markers.clear()
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
            samples, self.ipd_samples = self.ipd_samples, []
            markers, self.dist_markers = self.dist_markers, []

        # Send finalize command to the internal queue to decouple processing
        self.cmd_q.put(("FINALIZE", (samples, markers)))


    def set_timestamp(self, dist_point: dict) -> None:
        """Append a distance marker with the current timestamp to dist_markers.

        Args:
            dist_point: a dictionary with keys "state" and "distance".

        """
        string_state = dist_point.get("state")
        distance = dist_point.get("distance")

        # Parse the marker state
        match string_state:
            case "start":
                state = MarkerState.START
            case "stop":
                state = MarkerState.STOP
            case _:
                self.logger.error("Invalid marker state: %s", string_state)
                return

        if self.calib_start_t is None:
            self.logger.error("calib_start_t is not set.")
            return

        if distance is None:
            self.logger.error("Distance value is None.")
            return

        # Append the distance marker with the current timestamp
        t = monotonic() - self.calib_start_t

        if math.isfinite(distance) and distance >= 0.0:
            with self._buf_lock:
                self.dist_markers.append(DistanceMarker(t, state, distance))


# ---------- Internals ----------

    def _dequeue_cmds(self) -> None:
        """Dequeue commands from the command queue."""
        try:
            cmd, data = self.cmd_q.get(timeout=0.1)
            match cmd:
                case "FINALIZE":
                    ipd_samples, dist_markers = data
                    try:
                        self._finalize_calibration(ipd_samples, dist_markers)
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


    def _dequeue_ipd_data(self) -> None:
        """Dequeue IPD data from the IPD queue."""
        try:
            relative_ipd = self.ipd_q.get(timeout=self.cfg.gaze.ipd_queue_timeout)
            self._append_ipd(relative_ipd)
        except queue.Empty:
            pass


    def _append_ipd(self, relative_ipd: float) -> None:
        """Append the IPD to the ipd_samples list with a timestamp."""
        if self.calib_start_t is None:
            self.logger.error("calib_start_t is not set.")
            return
        t = monotonic() - self.calib_start_t
        with self._buf_lock:
            self.ipd_samples.append(IPDSample(t, relative_ipd))


    def _check_and_validate_distances(  # noqa: C901, PLR0911, PLR0912
        self,
        dist_markers: list[DistanceMarker],
    ) -> list[DistanceMarker]:
        """Check and validate the distance markers.

        Ensures that there are enough valid distance markers
        to perform calibration and that every distance has a start and stop marker.
        """
        if not dist_markers:
            self.logger.error("No distance markers provided.")
            return []

        # Sort by time to have a deterministic pass
        markers = sorted(dist_markers, key=lambda m: m.timestamp)

        validated: list[DistanceMarker] = []
        open_start: DistanceMarker | None = None
        distinct_distances: set[float] = set()

        for m in markers:
            if m.state == MarkerState.START:
                # Must not start a new interval while one is open
                if open_start is not None:
                    self.logger.error(
                        "Invalid markers: START at t=%.6f "
                        "before previous STOP (distance %.3f at t=%.6f).",
                        m.timestamp, open_start.distance, open_start.timestamp,
                    )
                    return []
                open_start = m
                validated.append(m)

            else:  # STOP
                if open_start is None:
                    self.logger.error(
                        "Invalid markers: STOP at t=%.6f without a matching START.",
                        m.timestamp,
                    )
                    return []

                # Distance must match the open interval
                if not np.isclose(m.distance, open_start.distance):
                    self.logger.error(
                        "Invalid markers: STOP distance %.6f does not match START distance %.6f.",
                        m.distance, open_start.distance,
                    )
                    return []

                # STOP must be strictly after START
                if m.timestamp <= open_start.timestamp:
                    self.logger.error(
                        "Invalid markers: STOP (t=%.6f) not after START "
                        "(t=%.6f) for distance %.6f.",
                        m.timestamp, open_start.timestamp, m.distance,
                    )
                    return []

                # Pair is valid: record STOP and close interval
                validated.append(m)
                distinct_distances.add(m.distance)
                open_start = None

        # No unclosed interval remaining
        if open_start is not None:
            self.logger.error(
                "Invalid markers: last START at t=%.6f (distance %.6f) has no matching STOP.",
                open_start.timestamp, open_start.distance,
            )
            return []

        # Require at least 3 distinct distances

        if len(distinct_distances) < self.min_distances_for_calib:
            self.logger.error(
                "Not enough distinct distances for calibration: got %d, need at least 3.",
                len(distinct_distances),
            )
            return []

        # Sanity check that validated list is even-length and alternates START/STOP
        if len(validated) % 2 != 0:
            self.logger.error("Internal error: validated marker list length is not even.")
            return []

        for i in range(0, len(validated), 2):
            if (
                validated[i].state != MarkerState.START or
                validated[i+1].state != MarkerState.STOP
            ):
                self.logger.error("Internal error: validated markers do not alternate START/STOP.")
                return []

        self.logger.info(
            "Validated %d intervals across %d distinct distances.",
            len(validated) // 2, len(distinct_distances),
        )

        return validated


    def _extract_ipd_dist_pairs(
        self,
        ipd_samples: list[IPDSample],
        dist_markers: list[DistanceMarker],
    ) -> tuple[dict[float, tuple[float, float, int]], dict[float, list[IPDSample]]]:
        """Extract IPD intervals from self.ipd_list and processes them.

        Compares timestamps between distance markers and IPD samples
        and extracts IPD within the time interval paired with the distance.
        Then it processes each interval using self._process_interval().
        """
        # 1) Match IPD samples with distance markers
        # 2) Compute a single processed IPD for each interval using self._process_interval()
        # 3) Return a dictionary of distance-IPD pairs, where ipd is tuple of (mean, std, n_samples)

        if not ipd_samples or not dist_markers:
            self.logger.error("Cannot extract pairs: empty samples or markers.")
            return {}, {}

        # Ensure time order
        samples = sorted(ipd_samples, key=lambda s: s.timestamp)
        markers = dist_markers

        pairs: dict[float, tuple[float, float, int]] = {}
        debug_pairs: dict[float, list[IPDSample]] = {}

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
            interval: list[IPDSample] = []
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

            pairs[distance] = (float(mean_val), float(std_val), int(n_used))
            debug_pairs[distance] = interval

            self.logger.debug(
                "Distance %.3f -> mean=%.6f, std=%.6f, n=%d (interval [%.4f, %.4f]).",
                distance, pairs[distance][0], pairs[distance][1], pairs[distance][2],
                start_m.timestamp, stop_m.timestamp,
            )

        if len(pairs) < self.min_distances_for_calib:
            self.logger.error(
                "Only %d distances produced valid data after processing (need ≥3).",
                len(pairs),
            )
            return {}, {}

        return pairs, debug_pairs


    def _process_interval(
        self,
        ipd_interval: list[IPDSample],
        distance: float,
    ) -> tuple[float, float, int] | None:
        """Process a single distance interval's collected IPD samples.

        Returns a tuple of (mean, std, n_used) if successful, or None if rejected.
        """
        n_total = len(ipd_interval)
        if n_total < self.cfg.gaze.ipd_min_samples:
            self.logger.warning("Not enough samples collected for distance. "
                "Collected %d, need at least %d.", n_total, self.cfg.gaze.ipd_min_samples)
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
        crop_n = int(n * self.cfg.gaze.buffer_crop_factor)
        if crop_n * 2 >= n:
            self.logger.warning(
                "Interval for distance %.2f invalid after cropping (n=%d, crop_n=%d).",
                distance, n, crop_n,
            )
            return None
        arr = arr[crop_n:-crop_n]

        if arr.size < self.cfg.gaze.ipd_min_samples:
            self.logger.warning(
                "Not enough samples after cropping for distance %.2f: have %d, need at least %d.",
                distance, arr.size, self.cfg.gaze.ipd_min_samples,
            )
            return None

        # Compute stats
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))

        # --- Validate sample quality ---
        if std_val > self.cfg.gaze.std_threshold:
            self.logger.warning("High standard deviation detected (%f).", std_val)
            return None

        return mean_val, std_val, len(arr)


    def _fit_model(self, ipd_dist_pairs: dict[float, tuple[float, float, int]]) -> bool:
        """Fit the model to the eye data.

        Uses the collected calibration data pairs to fit the inverse model.
        """
        if len(ipd_dist_pairs) < self.min_distances_for_calib:
            self.logger.error("Calibration: Not enough points to fit a model.")
            return False

        distances = np.array(list(ipd_dist_pairs.keys()), dtype=float)
        ipd_means = np.array([vals[0] for vals in ipd_dist_pairs.values()], dtype=float)

        model_params = inverse_model.fit(distances, ipd_means)
        if model_params is None or len(model_params) != 2:  # noqa: PLR2004
            self.logger.error("Calibration: Model fitting failed.")
            return False

        a, b = float(model_params[0]), float(model_params[1])

        self.cfg.set("gaze.model_params", (a, b))

        self.logger.info("Calibration: Model fitted successfully: %s", (a, b))

        return True


    def compensate_for_impairment(self) -> None:
        """Compensate for users visual impairment."""
        model_params = self.cfg.gaze.model_params

        if model_params is None or len(model_params) != 2:  # noqa: PLR2004
            self.logger.error("No valid model_params to compensate.")
            return

        a, b = float(model_params[0]), float(model_params[1])

        # If no impairment, copy through
        diop = float(self.cfg.gaze.diop_impairment)
        if diop > self.cfg.gaze.max_diop_impairment:
            diop = self.cfg.gaze.max_diop_impairment
            self.logger.warning("Diopter impairment capped to maximum of %f D.",
                self.cfg.gaze.max_diop_impairment)

        if diop == 0.0:
            self.cfg.gaze.corrected_model_params = (a, b)
            return

        if abs(diop) >= 1e-6:  # noqa: PLR2004
            focus_distance = 1.0 / diop  # meters; negative for myopia
            self.logger.info("Impairment: %.3f D (nominal focus at %.3f m).", diop, focus_distance)
        else:
            focus_distance = float("inf")

        # Gain from config; cast to float so your int in config still works
        gain = self.cfg.gaze.compensation_factor

        delta_b = gain * diop

        # Keep |delta_b| within a safe band (e.g., 5% of |b|)
        max_shift = self.cfg.gaze.max_shift_factor * max(1.0, abs(b))

        delta_b = min(delta_b, max_shift)
        delta_b = max(delta_b, -max_shift)

        b_new = b + delta_b
        a_new = a

        self.logger.info("Compensating for user diopter: %f (focus at %f m) "
            "with delta_b=%f. a=%f, b=%f -> a=%f, b=%f",
            self.cfg.gaze.diop_impairment, focus_distance, delta_b, a, b, a_new, b_new)

        self.cfg.set("gaze.corrected_model_params", (a_new, b_new))


    def _finalize_calibration(
        self,
        ipd_samples: list[IPDSample],
        dist_markers: list[DistanceMarker],
    ) -> None:
        """Finalize the calibration by processing.

        Averages and processes IPDs in each distance interval,
        creating distance-IPD pairs and fitting the model.
        """
        # Checks and validates for enough distances to fit the model
        validated_dist_markers = self._check_and_validate_distances(dist_markers)
        if not validated_dist_markers:
            self.logger.error("Calibration finalization aborted due to invalid distance markers.")
            return

        # Extracts IPD intervals by comparing timestamps and creates distance-IPD dictionary
        ipd_dist_pairs, _ = self._extract_ipd_dist_pairs(ipd_samples, validated_dist_markers)

        # Fit the model using the collected dict pairs
        if not self._fit_model(ipd_dist_pairs):
            self.logger.error("Calibration finalization aborted due to model fitting failure.")
            return

        # Apply compensation for visual impairment if needed
        if self.cfg.gaze.diop_impairment != 0.0:
            self.compensate_for_impairment()

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
        } and self.cfg.gaze.model_params is not None:
            # Re-apply compensation if impairment setting changes
            self.compensate_for_impairment()
