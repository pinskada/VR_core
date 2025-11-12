"""Gaze control and preprocessing module for VR Core on Raspberry Pi."""

import itertools
import queue
from queue import Queue, PriorityQueue
from threading import Event
from typing import Any, Optional
import time

import numpy as np

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.signals import GazeSignals
from vr_core.network.comm_contracts import MessageType
from vr_core.utilities.logger_setup import setup_logger


class GazePreprocess(BaseService):
    """Gaze control and preprocessing module for VR Core on Raspberry Pi."""

    def __init__(
        self,
        tracker_data_q: Queue,
        ipd_q: Queue,
        comm_router_q: PriorityQueue,
        pq_counter: itertools.count,
        gaze_signals: GazeSignals,
        imu_send_to_gaze_signal: Event,
        config: Config,
        ) -> None:

        super().__init__("GazePreprocess")
        self.logger = setup_logger("GazePreprocess")

        self.tracker_data_q = tracker_data_q
        self.ipd_q = ipd_q
        self.comm_router_q = comm_router_q
        self.pq_counter = pq_counter

        self.gaze_calib_s = gaze_signals.gaze_calib_s
        self.gaze_calc_s = gaze_signals.gaze_calc_s
        self.ipd_to_tcp_s = gaze_signals.ipd_to_tcp_s

        self.imu_send_to_gaze_signal = imu_send_to_gaze_signal

        self.cfg = config
        self._unsubscribe = config.subscribe("camera", self._on_config_changed)
        self._unsubscribe = config.subscribe("tracker_crop", self._on_config_changed)

        self.full_frame_width: int
        self.x_left_start: float
        self.y_left_start: float
        self.x_right_start: float
        self.y_right_start: float

        self.filtered_ipd: Optional[float] = None # Placeholder for the filtered Interpupillary Distance (IPD) value

        self.print_state = 0
        self.time = 0.0
        self.online = False # Flag to indicate if the system is online or offline

        #self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """
        Service start logic.
        """
        self.online = True
        self._ready.set()

        #self.logger.info("Service set ready.")


    def _run(self) -> None:
        """
        Run the gaze control service.
        """
        while not self._stop.is_set():
            self._unqueue_eye_data()


    def _on_stop(self):
        """Service stop logic."""
        self.online = False
        self._unsubscribe()
        #self.logger.info("Service stopping.")


    def is_online(self):
        return self.online


# ---------- Internals ----------

    def _unqueue_eye_data(self):
        """
        Unqueue eye data from the tracker data queue.
        """
        try:
            eye_data = self.tracker_data_q.get(timeout=self.cfg.gaze.tracker_data_timeout)
            (pupil_left, pupil_right) = eye_data

            if pupil_left is not None and pupil_right is not None:
                # self.logger.info("Preprocessing data.")
                self._get_relative_ipd(pupil_left, pupil_right)

        except queue.Empty:
            pass


    def _get_relative_ipd(self, pupil_left, pupil_right):
        """
        Get relative ipd of the eye data.
        """
        # self.logger.info("pupil_left: %s", pupil_left)
        # self.logger.info("pupil_right: %s", pupil_right)

        # Extract pupil centers
        x_left = pupil_left['pupil'][0][0]
        y_left = pupil_left['pupil'][0][1]
        x_right = pupil_right['pupil'][0][0]
        y_right = pupil_right['pupil'][0][1]

        # Calculate the full frame coordinates of the pupil centers
        full_x_left = self.x_left_start + x_left
        full_y_left = self.y_left_start + y_left

        full_x_right = self.x_right_start + x_right
        full_y_right = self.y_right_start + y_right

        # Calculate the Interpupillary Distance (IPD) in pixels
        ipd_px = np.linalg.norm([full_x_left - full_x_right, full_y_left - full_y_right])

        relat_ipd = ipd_px / self.full_frame_width # Normalize the IPD to the full frame width

        self._filter_ipd(float(relat_ipd)) # Apply filtering to the IPD value

        fps = 1 / (time.time() - self.time) if self.time != 0 else 0

        self.time = time.time()

        self.print_state += 1
        if self.print_state % 20 == 0:
            self.logger.info("Computed relative IPD: %s", self.filtered_ipd)
            self.logger.info("Gaze Preprocess FPS: %.2f", fps)

        if self.ipd_to_tcp_s.is_set():
            # Send the relative filtered IPD to the TCP module
            self.comm_router_q.put((6, next(self.pq_counter),
                MessageType.ipdPreview, self.filtered_ipd))

        if self.gaze_calib_s.is_set() and self.gaze_calc_s.is_set():
            self.logger.warning("Both gaze calibration and calculation signals are set, " \
            "skipping IPD processing.")
            return

        if self.gaze_calib_s.is_set() or self.gaze_calc_s.is_set():
            # Send the IPD to either calibration or main processing module
            self.ipd_q.put(self.filtered_ipd)


    def _filter_ipd(self, new_ipd: float):
        """Filter the IPD value using a simple moving average.

        Constant Alpha with range [0,1], where:
            1: fastest response, no filtering
            0: slowest response, maximum filtering
        """
        if self.filtered_ipd is None:
            # First value, no smoothing yet
            self.filtered_ipd = new_ipd
        else:
            self.filtered_ipd = (
                self.cfg.gaze.filter_alpha * new_ipd +
                (1 - self.cfg.gaze.filter_alpha) * self.filtered_ipd
            )


    def _copy_config_to_locals(self):
        """
        Copy configuration settings to local variables.
        """

        crop_left = self.cfg.tracker_crop.crop_left
        crop_right = self.cfg.tracker_crop.crop_right
        full_frame_width = self.cfg.camera.res_width
        full_frame_height = self.cfg.camera.res_height
        self.full_frame_width = full_frame_width

        self.x_left_start = crop_left[0][0] * full_frame_width
        self.y_left_start = crop_left[1][0] * full_frame_height
        self.x_right_start = crop_right[0][0] * full_frame_width
        self.y_right_start = crop_right[1][0] * full_frame_height


    # pylint: disable=unused-argument
    def _on_config_changed(self, path: str, old_val: Any, new_val: Any) -> None:
        """Handle configuration changes."""
        if (
            path == "tracker_crop.crop_left" or
            path == "tracker_crop.crop_right" or
            path == "camera.res_width" or
            path == "camera.res_height"
        ):
            self._copy_config_to_locals()
