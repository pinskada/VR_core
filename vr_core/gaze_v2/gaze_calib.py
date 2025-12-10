# ruff: noqa: ERA001, TRY400

"""Module for calibrating gaze angles."""

from __future__ import annotations

import csv
import json
import os
import queue
import threading
from dataclasses import asdict
from datetime import datetime
from queue import PriorityQueue, Queue
from time import monotonic
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.linalg import LinAlgError

import vr_core.gaze_v2.calibration_types as ct
from vr_core.base_service import BaseService
from vr_core.gaze_v2.calibrate_data import calibrate_data
from vr_core.network.comm_contracts import MessageType
from vr_core.ports.interfaces import IGazeService
from vr_core.ports.signals import GazeSignals
from vr_core.utilities.logger_setup import setup_logger

if TYPE_CHECKING:
    import itertools

    from vr_core.config_service.config import Config

# ---------- Calibration ----------

class GazeCalib(BaseService, IGazeService, GazeSignals):
    """Calibration handler for gaze distance measurements."""

    def __init__(  # noqa: PLR0913
        self,
        vectors_queue: Queue[ct.EyeVectors],
        comm_router_q: PriorityQueue[Any],
        pq_counter: itertools.count[int],
        gaze_signals: GazeSignals,
        config: Config,
        use_logger: bool = False,  # noqa: FBT001, FBT002
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

        self._buf_lock = threading.Lock()

        self.log_calibration = use_logger
        if self.log_calibration:
            log_id = datetime.now().strftime("%H%M%S")  # noqa: DTZ005
            self.log_path = "calib_log/calib_" + log_id + ".csv"
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)  # noqa: PTH103, PTH120

            self.log_results_path = "calib_log/results_" + log_id + ".json"
            os.makedirs(os.path.dirname(self.log_results_path), exist_ok=True)  # noqa: PTH103, PTH120

        # --- Lists for calibration data ---
        self.tracker_markers: list[ct.EyeVectorsWithTOA] = []
        self.scene_markers: list[ct.SceneMarkerWithTOA] = []

        self.calib_tracker_markers: list[ct.EyeVectorsWithTOA] = []
        self.calib_scene_markers: list[ct.SceneMarkerWithTOA] = []

        self.calib_start_t: float | None = None

        self.online = False

        # Calibration points for each type
        self.reference_calibrator: ct.CalibrationPair | None = None
        self.distance_calibrator: list[ct.CalibrationPair] = []
        self.angle_calibrator: list[ct.CalibrationPair] = []

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

            if self.gaze_calib_s.is_set():
                self._dequeue_vectors_data()
            else:
                # Sleep briefly to avoid busy waiting
                self._stop.wait(0.1)


    def _on_stop(self) -> None:
        """Stop the gaze calibration service."""
        self.online = False

        #self.logger.info("Service stopped.")


# ---------- Public APIs ----------

    def start_of_calibration(self) -> None:
        """Start the gaze calibration.

        Signals to start collecting data for calibration.
        During this phase, the system will gather eye_vectors,
        during which scene_markers will be sent.
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

        # self.logger.info(self.scene_markers)

        # Retrieve collected data safely
        with self._buf_lock:
            self.calib_tracker_markers, self.tracker_markers = self.tracker_markers, []
            self.calib_scene_markers, self.scene_markers = self.scene_markers, []

        # Send finalize command to the internal queue to decouple processing
        self.cmd_q.put("FINALIZE")


    def set_timestamp(self, dist_point: dict[str, Any]) -> None:
        """Append a scene marker with current toa to scene_markers.

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
        marker_with_toa = ct.SceneMarkerWithTOA(scene_marker=scene_marker, toa=t)

        with self._buf_lock:
            self.scene_markers.append(marker_with_toa)
            # self.logger.info(marker_with_toa)


# ---------- Internals ----------

    def _parse_scene_marker(self, raw: dict[str, Any]) -> ct.SceneMarker | None:  # noqa: PLR0911
        """Parse raw dict from Unity into a SceneMarker.

        Expected format (from Unity/CalibrationLogic):

            {
            "id": int,
            "state": "START" | "STOP",
            "type": "REF" | "DIST" | "ANG",
            "target_position": {
                "distance": float,
                "horizontal": float,
                "vertical": float
            }
            }
        """
        try:
            # --- id ---
            marker_id = raw["id"]
            marker_id = int(marker_id)

            # --- state ---
            state_raw = raw["state"]
            if not isinstance(state_raw, str):
                self.logger.error("Scene marker parsing failed: 'state' must be a string, got %r", state_raw)
                return None
            try:
                state = ct.MarkerState[state_raw]  # "START"/"STOP" -> enum
            except KeyError:
                self.logger.error("Scene marker parsing failed: invalid state %r", state_raw)
                return None

            # --- type ---
            type_raw = raw["type"]
            if not isinstance(type_raw, str):
                self.logger.error("Scene marker parsing failed: 'type' must be a string, got %r", type_raw)
                return None
            try:
                mtype = ct.MarkerType[type_raw]  # "REF"/"DIST"/"ANG" -> enum
            except KeyError:
                self.logger.error("Scene marker parsing failed: invalid type %r", type_raw)
                return None

            # --- target_position ---
            pos_raw = raw.get("target_position")
            if not isinstance(pos_raw, dict):
                self.logger.error("Scene marker parsing failed: invalid target_position %r", pos_raw)
                return None

            distance = float(pos_raw["distance"])
            horizontal = float(pos_raw["horizontal"])
            vertical = float(pos_raw["vertical"])

            pos = ct.TargetPosition(
                distance=distance,
                horizontal=horizontal,
                vertical=vertical,
            )

        except (KeyError, TypeError, ValueError) as e:
            self.logger.error("Scene marker parsing failed: %s", e)
            return None

        return ct.SceneMarker(
            id=marker_id,
            state=state,
            type=mtype,
            target_position=pos,
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
                        self.comm_router_q.put((8, next(self.pq_counter), MessageType.gazeSceneControl, "calib_failed"))
                        self.logger.exception("Finalize failed (expected type)")
                    except Exception:  # pylint: disable=broad-except
                        # Truly unexpected — still don't crash the service thread
                        self.comm_router_q.put((8, next(self.pq_counter), MessageType.gazeSceneControl, "calib_failed"))
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
            self.logger.info("_deque_vectors_data: %s", vector_data)
        except queue.Empty:
            pass


    def _append_vectors(self, vector_data: ct.EyeVectors) -> None:
        """Append the tracker eye vectors to the tracker_markers list with a toa."""
        if self.calib_start_t is None:
            self.logger.error("calib_start_t is not set.")
            return
        toa = monotonic() - self.calib_start_t
        with self._buf_lock:
            self.tracker_markers.append(ct.EyeVectorsWithTOA(toa, vector_data))
            self.logger.info("_append_data: %s", vector_data)



    def _validate_scene_markers(self) -> bool:  # noqa: C901, PLR0911
        """Check and validate the scene markers.

        Ensures that markers:
            - are in chronological order,
            - form non-overlapping START/STOP intervals,
            - have matching IDs for each START/STOP pair.

        Returns:
            bool: True if validation is successful, False otherwise.

        """
        # self.logger.info(self.calib_scene_markers)
        if not self.calib_scene_markers:
            self.logger.error("No scene markers provided.")
            return False

        # Sort by time-of-arrival to have a deterministic pass
        markers = sorted(self.calib_scene_markers, key=lambda m: m.toa)

        validated: list[ct.SceneMarkerWithTOA] = []
        open_start: ct.SceneMarkerWithTOA | None = None

        for m_toa in markers:
            sm = m_toa.scene_marker

            if sm.state == ct.MarkerState.START:
                # Must not start a new interval while one is open
                if open_start is not None:
                    self.logger.error(
                        "Invalid markers: START (id=%d) at t=%.6f before previous STOP "
                        "(id=%d at t=%.6f).",
                        sm.id,
                        m_toa.toa,
                        open_start.scene_marker.id,
                        open_start.toa,
                    )
                    return False

                open_start = m_toa
                validated.append(m_toa)

            else:  # STOP
                if open_start is None:
                    self.logger.error(
                        "Invalid markers: STOP (id=%d) at t=%.6f without a matching START.",
                        sm.id,
                        m_toa.toa,
                    )
                    return False

                sm_start = open_start.scene_marker

                # ID must match the open interval
                if sm.id != sm_start.id:
                    self.logger.error(
                        "Invalid markers: STOP (id=%d) does not match START (id=%d).",
                        sm.id,
                        sm_start.id,
                    )
                    return False

                # STOP must be strictly after START
                if m_toa.toa <= open_start.toa:
                    self.logger.error(
                        "Invalid markers: STOP (id=%d, t=%.6f) not after START (t=%.6f).",
                        sm.id,
                        m_toa.toa,
                        open_start.toa,
                    )
                    return False

                # Pair is valid: record STOP and close interval
                validated.append(m_toa)
                open_start = None

        # No unclosed interval remaining
        if open_start is not None:
            sm = open_start.scene_marker
            self.logger.error(
                "Invalid markers: last START (id=%d) at t=%.6f has no matching STOP.",
                sm.id,
                open_start.toa,
            )
            return False

        # Sanity check that validated list is even-length and alternates START/STOP
        if len(validated) % 2 != 0:
            self.logger.error("Internal error: validated marker list length is not even.")
            return False

        for i in range(0, len(validated), 2):
            if (
                validated[i].scene_marker.state != ct.MarkerState.START
                or validated[i + 1].scene_marker.state != ct.MarkerState.STOP
            ):
                self.logger.error(
                    "Internal error: validated markers do not alternate START/STOP.",
                )
                return False

        distinct_ids = {
            m.scene_marker.id for m in validated if m.scene_marker.state == ct.MarkerState.START
        }
        self.logger.info(
            "Validated %d intervals across %d distinct marker IDs.",
            len(validated) // 2,
            len(distinct_ids),
        )

        # Overwrite with the validated, ordered list
        self.calib_scene_markers = validated
        return True



    def _extract_marker_pairs(self) -> bool:  # noqa: C901
        """Create self.calibrators using calib_tracker_markers and calib_scene_markers.

        1. Takes the time interval from each calib_scene_markers START-STOP pair and selects
           all calib_tracker_markers that fall within this interval.
        2. Using self._process_interval(), a CalibrationPair is created for each interval
           consisting of a target position and aggregated eye vectors.
        3. Populates self.reference_calibrator, self.distance_calibrator and
           self.angle_calibrator by grouping CalibrationPairs by MarkerType of the
           original calib_scene_markers.
        """
        if not self.calib_tracker_markers:
            self.logger.error("Cannot extract pairs: empty tracker markers.")
            return False

        if not self.calib_scene_markers:
            self.logger.error("Cannot extract pairs: empty scene markers.")
            return False

        # Ensure time order for tracker samples
        samples = sorted(self.calib_tracker_markers, key=lambda s: s.toa)
        markers = self.calib_scene_markers

        # Reset outputs
        self.reference_calibrator = None
        self.distance_calibrator = []
        self.angle_calibrator = []

        s_idx = 0
        s_len = len(samples)

        # We assume _validate_scene_markers() has already ensured:
        # - markers are sorted
        # - they come in START/STOP pairs [0,1], [2,3], ...
        for i in range(0, len(markers), 2):
            start_m = markers[i]
            stop_m = markers[i + 1]

            sm = start_m.scene_marker  # meta (id, type, target_position)
            marker_id = sm.id
            marker_type = sm.type
            target_position = sm.target_position

            # Advance to first sample inside the interval
            while s_idx < s_len and samples[s_idx].toa < start_m.toa:
                s_idx += 1

            # Collect samples within [start, stop]
            interval_samples: list[ct.EyeVectorsWithTOA] = []
            j = s_idx
            while j < s_len and samples[j].toa <= stop_m.toa:
                interval_samples.append(samples[j])
                j += 1

            # Move head index forward for next interval (monotonic markers)
            s_idx = j

            if not interval_samples:
                self.logger.warning(
                    "No eye-vector samples found in interval [%.4f, %.4f] for marker id=%d.",
                    start_m.toa,
                    stop_m.toa,
                    marker_id,
                )
                return False

            # Strip timestamps; _process_interval only needs the EyeVectors themselves
            eye_vector_list = [s.eye_vectors for s in interval_samples]

            calib_pair = self._process_interval(
                eye_vector_list,
                target_position,
                marker_id,
                marker_type,
            )
            if calib_pair is None:
                self.logger.warning(
                    "Interval for marker id=%d rejected by processing; skipping.",
                    marker_id,
                )
                return False

            self.logger.debug(
                "Marker id=%d (type=%s, dist=%.3f, hor=%.3f, ver=%.3f) "
                "produced a calibration pair.",
                marker_id,
                marker_type.name,
                target_position.distance,
                target_position.horizontal,
                target_position.vertical,
            )

            # Sort into reference / distance / angle calibrators
            if marker_type == ct.MarkerType.REF:
                if self.reference_calibrator is not None:
                    self.logger.warning(
                        "Multiple REF markers detected; keeping the first, ignoring id=%d.",
                        marker_id,
                    )
                else:
                    self.reference_calibrator = calib_pair

            elif marker_type == ct.MarkerType.DIST:
                self.distance_calibrator.append(calib_pair)

            elif marker_type == ct.MarkerType.ANG:
                self.angle_calibrator.append(calib_pair)

        if (
            self.reference_calibrator is None
            and not self.distance_calibrator
            and not self.angle_calibrator
        ):
            self.logger.error("No valid marker intervals produced any calibration pairs.")
            return False

        self.logger.info(
            "Extracted calibration pairs: ref=%s, dist=%d, ang=%d.",
            "yes" if self.reference_calibrator is not None else "no",
            len(self.distance_calibrator),
            len(self.angle_calibrator),
        )

        return True


    def _process_interval(
        self,
        eye_vector_list: list[ct.EyeVectors],
        target_position: ct.TargetPosition,
        marker_id: int,
        marker_type: ct.MarkerType,
    ) -> ct.CalibrationPair | None:
        """Process a single scene interval's collected tracker markers.

        Creates a single CalibrationPair for the given target position and eye vectors.
        Computes means and stds for the eye vectors and validates their integrity.
        If invalid, returns None.

        Args:
            eye_vector_list:
                List of EyeVectors collected during the interval.
            target_position:
                The target position during the interval.
            marker_id:
                The ID of the marker.
            marker_type:
                The type of the marker.

        Returns:
            CalibrationPair: Mean of the eye vectors, target position and stats if valid.
            None: If the data is invalid.

        """
        n_total = len(eye_vector_list)
        if n_total < self.cfg.gaze2.vector_min_samples:
            self.logger.warning(
                "Not enough samples collected for target (dist=%.3f, hor=%.3f, ver=%.3f). "
                "Collected %d, need at least %d.",
                target_position.distance,
                target_position.horizontal,
                target_position.vertical,
                n_total,
                self.cfg.gaze2.vector_min_samples,
            )
            return None

        # Build array: columns = [Lx, Ly, Rx, Ry]
        arr = np.empty((n_total, 4), dtype=float)

        for idx, ev in enumerate(eye_vector_list):
            lv = ev.left_eye_vector
            rv = ev.right_eye_vector

            arr[idx, 0] = lv.dx
            arr[idx, 1] = lv.dy
            arr[idx, 2] = rv.dx
            arr[idx, 3] = rv.dy

        # Remove rows that contain any NaN/Inf
        finite_mask = np.isfinite(arr).all(axis=1)
        if not finite_mask.all():
            n_removed = int(np.count_nonzero(~finite_mask))
            arr = arr[finite_mask]
            self.logger.debug(
                "Removed %d non-finite vector samples (NaN/Inf) for target (dist=%.3f, hor=%.3f, ver=%.3f).",
                n_removed,
                target_position.distance,
                target_position.horizontal,
                target_position.vertical,
            )

        # If all values are invalid, reject interval
        if arr.shape[0] == 0:
            self.logger.warning(
                "All vector samples invalid (NaN/Inf) for target (dist=%.3f, hor=%.3f, ver=%.3f).",
                target_position.distance,
                target_position.horizontal,
                target_position.vertical,
            )
            return None

        # Edge crop in time to remove transient samples at start/end
        n = arr.shape[0]
        crop_n = int(n * self.cfg.gaze2.buffer_crop_factor)
        if crop_n * 2 >= n:
            self.logger.warning(
                "Interval for target (dist=%.3f, hor=%.3f, ver=%.3f) invalid after cropping "
                "(n=%d, crop_n=%d).",
                target_position.distance,
                target_position.horizontal,
                target_position.vertical,
                n,
                crop_n,
            )
            return None

        arr = arr[crop_n:-crop_n, :]

        if self.log_calibration:
            self._log_interval_to_csv(
                marker_id=marker_id,
                marker_type=marker_type,
                target_position=target_position,
                arr=arr,
            )

        if arr.shape[0] < self.cfg.gaze2.vector_min_samples:
            self.logger.warning(
                "Not enough samples after cropping for target (dist=%.3f, hor=%.3f, ver=%.3f): "
                "have %d, need at least %d.",
                target_position.distance,
                target_position.horizontal,
                target_position.vertical,
                arr.shape[0],
                self.cfg.gaze2.vector_min_samples,
            )
            return None

        # Compute stats per column
        means = np.mean(arr, axis=0)
        stds = np.std(arr, axis=0)
        n_used = int(arr.shape[0])

        # Reject interval if any component is too noisy
        max_std = float(np.max(stds))
        if max_std > self.cfg.gaze2.std_threshold:
            self.logger.warning(
                "High standard deviation detected (max std=%f) "
                "for target (dist=%.3f, hor=%.3f, ver=%.3f).",
                max_std,
                target_position.distance,
                target_position.horizontal,
                target_position.vertical,
            )
            return None

        # Construct mean EyeVectors as the aggregated calibration value
        mean_left = eye_vector_list[0].left_eye_vector.__class__(
            dx=float(means[0]),
            dy=float(means[1]),
        )
        mean_right = eye_vector_list[0].right_eye_vector.__class__(
            dx=float(means[2]),
            dy=float(means[3]),
        )
        mean_eye_vectors = ct.EyeVectors(
            left_eye_vector=mean_left,
            right_eye_vector=mean_right,
        )

        # Build stats object
        stats = ct.CalibStats(
            n_samples=n_used,
            std_left=(float(stds[0]), float(stds[1])),
            std_right=(float(stds[2]), float(stds[3])),
        )

        return ct.CalibrationPair(
            target_position=target_position,
            eye_vectors=mean_eye_vectors,
            marker_id=marker_id,
            calib_stats=stats,
        )


    def _log_interval_to_csv(
        self,
        marker_id: int,
        marker_type: ct.MarkerType,
        target_position: ct.TargetPosition,
        arr: np.ndarray[Any, np.dtype[np.float64]],
    ) -> None:
        """Append cropped interval samples to a CSV file.

        arr shape: (n_samples, 4) with columns [Lx, Ly, Rx, Ry].
        """
        # Create file with header if it doesn't exist yet
        file_exists = os.path.exists(self.log_path)  # noqa: PTH110

        with open(self.log_path, "a", newline="") as f:  # noqa: PTH123
            writer = csv.writer(f)

            if not file_exists:
                writer.writerow(
                    [
                        "marker_id",
                        "marker_type",
                        "distance",
                        "horizontal",
                        "vertical",
                        "eye",
                        "sample_index",
                        "dx",
                        "dy",
                    ],
                )

            dist = target_position.distance
            hor = target_position.horizontal
            ver = target_position.vertical

            for idx, row in enumerate(arr):
                lx, ly, rx, ry = row

                writer.writerow(
                    [marker_id, marker_type.name, dist, hor, ver, "L", idx, lx, ly],
                )
                writer.writerow(
                    [marker_id, marker_type.name, dist, hor, ver, "R", idx, rx, ry],
                )


    def _finalize_calibration(self) -> None:
        """Finalize the calibration by processing.

        Runs the whole process of validating and pairing the data.
        """
        # Checks and validates for enough distances to fit the model
        if not self._validate_scene_markers():
            self.logger.warning(
                "Calibration finalization aborted due to invalid scene markers.",
            )
            self.comm_router_q.put((8, next(self.pq_counter), MessageType.gazeSceneControl, "calib_failed"))
            return

        # Extracts the intervals by comparing timestamps and poppulating the three calibrators
        if not self._extract_marker_pairs():
            self.logger.warning(
                "Calibration finalization aborted: failed to extract marker pairs.",
            )
            self.comm_router_q.put((8, next(self.pq_counter), MessageType.gazeSceneControl, "calib_failed"))
            return

        if (
            self.reference_calibrator is None
            or not self.distance_calibrator
            or not self.angle_calibrator
        ):
            self.logger.error(
                "Calibration finalization aborted: no valid calibration pairs.",
            )
            self.comm_router_q.put((8, next(self.pq_counter), MessageType.gazeSceneControl, "calib_failed"))
            return

        calibrator = ct.Calibrator(
            ref_calibrator=self.reference_calibrator,
            dist_calibrators=self.distance_calibrator,
            angle_calibrators=self.angle_calibrator,
        )

        # Calibrate
        try:
            calibrated_data = calibrate_data(calibrator)
        except (ValueError, TypeError, LinAlgError, OverflowError) as e:
            self.logger.warning("Calibration failed: %s", e)
            self.comm_router_q.put((8, next(self.pq_counter), MessageType.gazeSceneControl, "calib_failed"))
            if self.log_calibration:
                self.save_calibrator_and_data_to_json(calibrator, None)
            return

        calibrated_data_dict = asdict(calibrated_data)

        self.comm_router_q.put((8, next(self.pq_counter), MessageType.calibData, calibrated_data_dict))
        if self.log_calibration:
            self.save_calibrator_and_data_to_json(calibrator, calibrated_data)

        # Signal to GazeControl that calibration is finalized
        self.calib_finalized_s.set()


    def save_calibrator_and_data_to_json(
        self,
        calibrator: ct.Calibrator,
        calibrated_data: ct.CalibratedData | None,
    ) -> None:
        """Save the calibrator and calibrated data to JSON.

        If calibration failed, only the calibrator is stored (calibrated_data=None).
        """
        # log_results_path is created in __init__ when log_calibration is True
        if not hasattr(self, "log_results_path"):
            self.logger.error(
                "log_results_path is not set; cannot save calibration results.",
            )
            return

        try:
            payload: dict[str, Any] = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),  # noqa: DTZ005
                "calibrator": asdict(calibrator),
                "calibrated_data": asdict(calibrated_data) if calibrated_data is not None else None,
            }

            # Ensure directory exists (defensive; it's already created in __init__)
            os.makedirs(os.path.dirname(self.log_results_path), exist_ok=True)  # noqa: PTH103, PTH120

            with open(self.log_results_path, "w", encoding="utf-8") as f:  # noqa: PTH123
                json.dump(payload, f, indent=2)

            self.logger.info(
                "Calibration results saved to %s (has calibrated_data=%s).",
                self.log_results_path,
                "yes" if calibrated_data is not None else "no",
            )

        except Exception:
            # Don't crash calibration just because logging failed
            self.logger.exception("Failed to save calibration results to JSON.")
