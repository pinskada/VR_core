"""Gaze control module."""

from threading import Event

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.interfaces import IGazeControl, IGazeService
from vr_core.ports.signals import GazeSignals
from vr_core.utilities.logger_setup import setup_logger


class GazeControl(BaseService, IGazeControl):
    """Gaze control module."""

    def __init__(
        self,
        gaze_signals: GazeSignals,
        imu_send_to_gaze_signal: Event,
        i_gaze_calib: IGazeService,
        config: Config,
    ) -> None:

        super().__init__("GazePreprocess")
        self.logger = setup_logger("GazePreprocess")

        self.calib_finalized_s = gaze_signals.calib_finalized_s
        self.gaze_calib_s = gaze_signals.gaze_calib_s
        self.gaze_calc_s = gaze_signals.gaze_calc_s
        self.ipd_to_tcp_s = gaze_signals.ipd_to_tcp_s

        self.imu_send_to_gaze_s = imu_send_to_gaze_signal

        self.i_gaze_calib = i_gaze_calib

        self.cfg = config

        #self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Service start logic."""
        self.imu_send_to_gaze_s.clear()
        self.gaze_calib_s.clear()
        self.gaze_calc_s.clear()
        self.ipd_to_tcp_s.clear()

        self._ready.set()

        #self.logger.info("Service set ready.")


    def _run(self) -> None:
        """Run the gaze control service."""

        while not self._stop.is_set():
            self._stop.wait(0.1)


    def _on_stop(self):
        """Service stop logic."""
        self.imu_send_to_gaze_s.clear()
        self.gaze_calib_s.clear()
        self.gaze_calc_s.clear()
        self.ipd_to_tcp_s.clear()

        #self.logger.info("Service stopping.")


# ---------- Public APIs ----------

    def gaze_control(self, msg: dict) -> None:
        """Control the gaze module."""
        command = msg.get("command")

        match command:
            case "start_calibration":
                self._start_calibration()
            case "end_calibration":
                self._end_calibration()
            case "set_timestamp":
                dist_point = msg.get("dist_point", {})
                if isinstance(dist_point, dict):
                    self.i_gaze_calib.set_timestamp(dist_point)
            case "start_gaze_calc":
                self._start_gaze_calc()
            case "ipd_to_tcp_requested":
                self._ipd_to_tcp_requested()
            case "ipd_to_tcp_aborted":
                self._ipd_to_tcp_aborted()


# ---------- Internals ----------

    def _start_calibration(self) -> None:
        """Start the calibration process."""
        self.logger.info("Starting calibration process.")
        self.gaze_calc_s.clear()
        self.i_gaze_calib.start_of_calibration()


    def _end_calibration(self) -> None:
        """End the calibration process."""
        self.logger.info("Ending calibration process.")
        self.i_gaze_calib.end_of_calibration()


    def _start_gaze_calc(self) -> None:
        """Starts computing and providing gaze estimate."""
        if not self.calib_finalized_s.is_set():
            self.logger.warning("Calibration not finalized. Gaze calculation aborted.")
            return

        self.logger.info("Starting gaze calculation.")
        self.gaze_calc_s.set()
        self.imu_send_to_gaze_s.set()


    def _ipd_to_tcp_requested(self) -> None:
        """Handles IPD to TCP request."""
        self.logger.info("IPD to TCP request received.")
        self.ipd_to_tcp_s.set()


    def _ipd_to_tcp_aborted(self) -> None:
        """Handles IPD to TCP abort."""
        self.logger.info("IPD to TCP abort request.")
        self.ipd_to_tcp_s.clear()
