# ruff: noqa: ERA001

"""Module for computing eye vectors from tracker data."""

from __future__ import annotations

import queue
from queue import PriorityQueue, Queue
from typing import TYPE_CHECKING, Any

import vr_core.gaze_v2.calibration_types as ct
from vr_core.base_service import BaseService
from vr_core.network.comm_contracts import MessageType
from vr_core.utilities.logger_setup import setup_logger

if TYPE_CHECKING:
    import itertools
    from threading import Event

    from vr_core.config_service.config import Config
    from vr_core.eye_tracker import tracker_types as tt
    from vr_core.ports.signals import GazeSignals


class GazePreprocess(BaseService):
    """Gaze control and preprocessing module for VR Core on Raspberry Pi."""

    def __init__(  # noqa: PLR0913
        self,
        tracker_data_q: Queue[tt.TwoSideTrackerData],
        eye_vector_q: Queue[ct.EyeVectors],
        comm_router_q: PriorityQueue[Any],
        pq_counter: itertools.count[int],
        gaze_signals: GazeSignals,
        imu_send_to_gaze_signal: Event,
        config: Config,
        ) -> None:
        """Initialize the GazePreprocess service."""
        super().__init__("GazePreprocess")
        self.logger = setup_logger("GazePreprocess")

        self.tracker_data_q = tracker_data_q
        self.eye_vector_q = eye_vector_q
        self.comm_router_q = comm_router_q
        self.pq_counter = pq_counter

        self.gaze_calib_s = gaze_signals.gaze_calib_s
        self.gaze_calc_s = gaze_signals.gaze_calc_s
        self.ipd_to_tcp_s = gaze_signals.ipd_to_tcp_s

        self.imu_send_to_gaze_signal = imu_send_to_gaze_signal

        self.cfg = config

        self.filtered_e_v: ct.EyeVectors | None = None

        self.online = False # Flag to indicate if the system is online or offline

        #self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Service start logic."""
        self.online = True
        self._ready.set()

        #self.logger.info("Service set ready.")


    def _run(self) -> None:
        """Run the gaze control service."""
        while not self._stop.is_set():
            self._unqueue_eye_data()


    def _on_stop(self) -> None:
        """Service stop logic."""
        self.online = False
        #self.logger.info("Service stopping.")


    def is_online(self) -> bool:
        """Check if the service is online."""
        return self.online


# ---------- Internals ----------

    def _unqueue_eye_data(self) -> None:
        """Unqueue eye data from the tracker data queue."""
        try:
            eye_data = self.tracker_data_q.get(timeout=self.cfg.gaze2.tracker_data_timeout)

            if eye_data is not None:
                # self.logger.info("Preprocessing data.")
                self._process_tracker_data(eye_data)

        except queue.Empty:
            pass


    def _process_tracker_data(self, eye_data: tt.TwoSideTrackerData) -> None:
        """Compute CRs centroids and eye vectors for both eyes.

        Args:
            eye_data: The tracker data containing eye information.

        """
        left_eye = eye_data.left_eye_data
        right_eye = eye_data.right_eye_data

        if left_eye.pupil is None or right_eye.pupil is None:
            return

        try:
            left_cr_centroid = self._compute_cr_centroid(left_eye.crs)
            right_cr_centroid = self._compute_cr_centroid(right_eye.crs)
        except ValueError as e:
            self.logger.warning("CR centroid computation error: %s, skipping eye vector calculation.", e)
            return

        left_pupil_center = left_eye.pupil.center
        right_pupil_center = right_eye.pupil.center

        left_eye_vector_x = left_pupil_center[0] - left_cr_centroid[0]
        left_eye_vector_y = left_pupil_center[1] - left_cr_centroid[1]
        left_eye_vector = ct.EyeVector(left_eye_vector_x, left_eye_vector_y)

        right_eye_vector_x = right_pupil_center[0] - right_cr_centroid[0]
        right_eye_vector_y = right_pupil_center[1] - right_cr_centroid[1]
        right_eye_vector = ct.EyeVector(right_eye_vector_x, right_eye_vector_y)

        eye_vectors = ct.EyeVectors(left_eye_vector, right_eye_vector)

        self._filter_vectors(eye_vectors)

        if self.ipd_to_tcp_s.is_set():
            # Send the relative filtered IPD to the TCP module
            self.comm_router_q.put((6, next(self.pq_counter),
            MessageType.gazeData, self.filtered_e_v))

        if self.gaze_calib_s.is_set() and self.gaze_calc_s.is_set():
            self.logger.warning("Both gaze calibration and calculation signals are set, "
            "skipping IPD processing.")
            return

        if (self.gaze_calib_s.is_set() or self.gaze_calc_s.is_set()) and self.filtered_e_v is not None:
            # Send the IPD to either calibration or main processing module
            self.eye_vector_q.put(self.filtered_e_v)


    def _compute_cr_centroid(
        self,
        crs: list[tt.CrData],
    ) -> tuple[float, float]:
        """Compute the centroid of corneal reflections.

        Args:
            crs: List of corneal reflection data.

        Returns:
            Tuple of (x, y) coordinates of the centroid.

        """
        if not crs:
            error = "No corneal reflections available to compute centroid."
            raise ValueError(error)

        x_coords = [cr.center[0] for cr in crs]
        y_coords = [cr.center[1] for cr in crs]

        centroid_x = sum(x_coords) / len(crs)
        centroid_y = sum(y_coords) / len(crs)

        return (centroid_x, centroid_y)


    def _filter_vectors(self, eye_vectors: ct.EyeVectors) -> None:
        """Exponential smoothing of eye vectors.

        The smoothing factor alpha depends on whether we are in calibration
        or runtime mode:
            - gaze_calib_s set   -> cfg.gaze2.filter_alpha_calib
            - gaze_calc_s set    -> cfg.gaze2.filter_alpha_calc

        The result is stored in self.filtered_e_v.
        """
        # Decide which alpha to use
        calib_on = self.gaze_calib_s.is_set()
        calc_on = self.gaze_calc_s.is_set()

        if calib_on and not calc_on:
            alpha = float(self.cfg.gaze2.filter_alpha_calib)
        elif calc_on and not calib_on:
            alpha = float(self.cfg.gaze2.filter_alpha_calc)
        elif calib_on and calc_on:
            # This “shouldn't” happen (and you guard against it higher up),
            # but be defensive: log and prefer calibration alpha.
            self.logger.warning(
                "Both gaze_calib_s and gaze_calc_s are set in _filter_vectors; "
                "using calibration alpha.",
            )
            alpha = float(self.cfg.gaze2.filter_alpha_calib)
        else:
            # Neither mode active - default to runtime alpha, or no filtering.
            alpha = float(self.cfg.gaze2.filter_alpha_calc)

        # Clamp alpha to a safe range
        if alpha <= 0.0:
            # alpha <= 0 -> no smoothing, just take the new sample
            self.filtered_e_v = eye_vectors
            return
        if alpha >= 1.0:
            # alpha >= 1 -> full smoothing to new sample as well
            self.filtered_e_v = eye_vectors
            return

        # If this is the first sample, just initialize the filtered state
        if self.filtered_e_v is None:
            self.filtered_e_v = eye_vectors
            return

        prev = self.filtered_e_v
        cur = eye_vectors

        def smooth_sample(prev_s: ct.EyeVector, cur_s: ct.EyeVector) -> ct.EyeVector:
            return ct.EyeVector(
                dx=(1.0 - alpha) * prev_s.dx + alpha * cur_s.dx,
                dy=(1.0 - alpha) * prev_s.dy + alpha * cur_s.dy,
            )

        self.filtered_e_v = ct.EyeVectors(
            left_eye_vector=smooth_sample(prev.left_eye_vector, cur.left_eye_vector),
            right_eye_vector=smooth_sample(prev.right_eye_vector, cur.right_eye_vector),
        )
