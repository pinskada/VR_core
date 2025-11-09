"""Gaze calculation module."""

import itertools
from queue import Queue, PriorityQueue
import queue
import time

from vr_core.network.comm_contracts import MessageType
from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.signals import GazeSignals
from vr_core.utilities.logger_setup import setup_logger
from vr_core.gaze.models import inverse_model


class GazeCalc(BaseService):
    """Gaze calculation module."""
    def __init__(
        self,
        ipd_q: Queue,
        esp_cmd_q: Queue,
        comm_router_q: PriorityQueue,
        pq_counter: itertools.count,
        gyro_mag_q: Queue,
        gaze_signals: GazeSignals,
        config: Config,
    ) -> None:
        super().__init__("GazeCalc")
        self.logger = setup_logger("GazeCalc")

        self.ipd_q = ipd_q
        self.esp_cmd_q = esp_cmd_q
        self.comm_router_q = comm_router_q
        self.pq_counter = pq_counter
        self.gyro_mag_q = gyro_mag_q

        self.gaze_calc_s = gaze_signals.gaze_calc_s
        self.gaze_to_tcp_s = gaze_signals.gaze_to_tcp_s

        self.cfg = config

        # Flag to indicate if the tracker is trusted or not based on gyroscope data
        self.trust_tracker: bool

        self._untrust_until = 0.0

        self.online = False # Flag to indicate if the system is online or offline

        #self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self):
        """Handle service start."""

        self.online = True
        self.trust_tracker = True
        self._ready.set()
        #self.logger.info("Service started.")


    def _run(self):
        """Main service loop."""

        while not self._stop.is_set():
            if self.gaze_calc_s.is_set():
                self._dequeue_gyro()
                self._dequeue_ipd()
            self._stop.wait(self.cfg.gaze.ipd_queue_timeout)


    def _on_stop(self):
        """Handle service stop."""

        self.online = False
        #self.logger.info("Service stopped.")


    def is_online(self):
        return self.online


# ---------- Internals ----------

    def _dequeue_gyro(self):
        """Dequeue gyroscope data."""

        try:
            imu_data = self.gyro_mag_q.get_nowait()
            if imu_data:
                gyro_data = imu_data.get("gyro")
                if gyro_data:
                    self._gyro_handler(gyro_data)
        except queue.Empty:
            return


    def _dequeue_ipd(self):
        """Dequeue IPD data."""

        try:
            ipd = self.ipd_q.get_nowait()
            if ipd:
                self._process_eye_data(ipd)
        except queue.Empty:
            return


    def _process_eye_data(self, ipd: float):
        """
        Process the eye data.
        """

        if not self.cfg.gaze.model_params:
            self.logger.error("Model parameters not set. Cannot process eye data.")
            return

        if self.trust_tracker:

            # Calculate distance using the inverse model
            gaze_distance = inverse_model.predict(ipd, self.cfg.gaze.model_params)

            if self.gaze_to_tcp_s.is_set():
                # Send the gaze distance over tcp
                self.comm_router_q.put((8, next(self.pq_counter),
                    MessageType.gazeData, gaze_distance))

            # Send the gaze distance to the ESP32
            self.esp_cmd_q.put(gaze_distance)


    def _gyro_handler(self, input_gyro_data):
        """
        Update trust based on gyroscope rotation speed.
        gyro_data: (x_rotation, y_rotation, z_rotation) in deg/s
        """

        now = time.time()

        x_rotation = input_gyro_data.get("x")
        y_rotation = input_gyro_data.get("y")
        z_rotation = input_gyro_data.get("z")

        # Calculate total rotation speed
        total_rotation = (x_rotation**2 + y_rotation**2 + z_rotation**2)**0.5

        # Update trust based on thresholds
        if total_rotation > self.cfg.gaze.gyro_thr_high:
            # Disable tracker trust if rotation exceeds high threshold
            self.trust_tracker = False
            # Set the time until the tracker can be trusted again
            self._untrust_until = now + self.cfg.gaze.settle_time_s

        # Re-enable tracker trust if rotation is below low threshold and settle time has passed
        elif total_rotation < self.cfg.gaze.gyro_thr_low and now >= self._untrust_until:
            self.trust_tracker = True
