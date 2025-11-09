"""Launches and monitors the eye tracker processes."""

from multiprocessing import Process
import multiprocessing as mp
import queue
from typing import Optional, Literal

from vr_core.eye_tracker.run_eyeloop import run_eyeloop
from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.signals import EyeTrackerSignals, TrackerSignals
from vr_core.ports.interfaces import ITrackerService
from vr_core.utilities.logger_setup import setup_logger


TrackerState = Literal["idle","starting","running","stopping","error"]

class TrackerProcess(BaseService, ITrackerService):
    """Launches and monitors the eye tracker processes."""
    def __init__(
        self,
        tracker_cmd_q_l: mp.Queue,
        tracker_cmd_q_r: mp.Queue,
        tracker_resp_q_l: mp.Queue,
        tracker_resp_q_r: mp.Queue,
        tracker_health_q: queue.Queue,
        eye_tracker_signals: EyeTrackerSignals,
        tracker_signals: TrackerSignals,
        config: Config,
    ) -> None:
        super().__init__(name="TrackerProcess")

        self.logger = setup_logger("TrackerProcess")

        self.tracker_cmd_q_l = tracker_cmd_q_l
        self.tracker_cmd_q_r = tracker_cmd_q_r

        self.tracker_resp_q_l = tracker_resp_q_l
        self.tracker_resp_q_r = tracker_resp_q_r

        self.tracker_health_q = tracker_health_q

        self.eye_ready_s_l = tracker_signals.eye_ready_l
        self.eye_ready_s_r = tracker_signals.eye_ready_r

        self.tracker_shm_is_closed_s_l = eye_tracker_signals.tracker_shm_is_closed_l
        self.tracker_shm_is_closed_s_r = eye_tracker_signals.tracker_shm_is_closed_r

        self.tracker_running_s_l = tracker_signals.tracker_running_l
        self.tracker_running_s_r = tracker_signals.tracker_running_r

        self.first_frame_processed_s_l = tracker_signals.first_frame_processed_l
        self.first_frame_processed_s_r = tracker_signals.first_frame_processed_r

        self.cfg = config

        self.proc_left: Optional[Process] = None
        self.proc_right: Optional[Process] = None

        self.running_left = False
        self.running_right = False

        self.tracker_state: TrackerState = "idle"
        self.last_error: Optional[str] = None

        self.online = False

        #self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Starts the Eyeloop processes."""

        self.online = True
        self._ready.set()
        #self.logger.info("Service _ready is set.")


    def _run(self) -> None:
        """Main loop to monitor Eyeloop processes."""
        while not self._stop.is_set():
            self._monitor_children()
            self._drain_health_bus()
            self._stop.wait(self.cfg.tracker.health_check_interval)


    def _on_stop(self) -> None:
        """Stops the Eyeloop processes."""
        #self.logger.info("Service stopping.")
        self.online = False
        if not self.tracker_state == "idle":
            self.stop_tracker()


    # ---------- Public API (ITrackerService) ----------

    def start_tracker(
        self,
        test_mode: bool = False
    ) -> None:
        """Starts the tracker processes."""

        #self.logger.info("Starting tracker processes.")

        if self.tracker_state in ("starting","running"):
            self.logger.warning("Start requested but process already %s.", self.tracker_state)
            return

        self.tracker_state = "starting"
        self.last_error = None

        # Left
        try:
            self.proc_left = Process(
                target=run_eyeloop,
                args=("Left",
                      self.cfg.tracker.importer_name,
                      self.cfg.tracker.sharedmem_name_left,
                      self.cfg.tracker.blink_calibration_L,
                      self.tracker_cmd_q_l,
                      self.tracker_resp_q_l,
                      self.eye_ready_s_l,
                      self.tracker_shm_is_closed_s_l,
                      self.tracker_running_s_l,
                      test_mode
                ),
                daemon=False,
            )
            self.proc_left.start()
            self.running_left = True
            self.logger.info("Left EyeLoop started (pid=%d).", self.proc_left.pid)
        except (OSError, RuntimeError) as e:
            self.running_left = False
            self.tracker_state = "error"
            self.last_error = f"start left failed: {e!r}"
            self.logger.error("Failed to initialize left Eyeloop processes.")
            return

        # Right
        try:
            self.proc_right = Process(
                target=run_eyeloop,
                args=("Right",
                      self.cfg.tracker.importer_name,
                      self.cfg.tracker.sharedmem_name_right,
                      self.cfg.tracker.blink_calibration_R,
                      self.tracker_cmd_q_r,
                      self.tracker_resp_q_r,
                      self.eye_ready_s_r,
                      self.tracker_shm_is_closed_s_r,
                      self.tracker_running_s_r,
                      test_mode
                    ),
                daemon=False,
            )
            self.proc_right.start()
            self.running_right = True
            self.logger.info("Right EyeLoop started (pid=%d).", self.proc_right.pid)
        except (OSError, RuntimeError) as e:
            self.running_right = False
            self.tracker_state = "error"
            self.last_error = f"start right failed: {e!r}"
            self.logger.error("Failed to initialize right Eyeloop processes.")
            self._terminate_side("left")
            return

        if not self.tracker_running_s_l.wait(10):
            self.logger.error("Left Eyeloop didn't start up properly, shutting down.")
            return

        if not self.tracker_running_s_r.wait(10):
            self.logger.error("Right Eyeloop didn't start up properly, shutting down.")
            return

        self.tracker_state = "running"


    def stop_tracker(self) -> None:
        """Stops the tracker processes."""
        #self.logger.info("Stopping tracker processes.")

        if self.tracker_state in ("idle","stopping"):
            self.logger.warning("Stop requested but already %s.", self.tracker_state)
            return

        self.tracker_state = "stopping"

        self._terminate_side("left")
        self._terminate_side("right")

        self.tracker_state = "idle"
        self.running_left = False
        self.running_right = False


    # ---------- Internals ----------

    def _terminate_side(self, side: str) -> None:
        """Terminates the Eyeloop process for the given side."""

        proc = self.proc_left if side == "left" else self.proc_right
        if not proc:
            return


        if side == "left":
            self.tracker_cmd_q_l.put_nowait(
                {"type": "close"},
            )
        elif side == "right":
            self.tracker_cmd_q_r.put_nowait(
                {"type": "close"},
            )

        try:
            if proc.is_alive():
                try:
                    proc.terminate()
                except (ProcessLookupError, PermissionError, OSError) as e:
                    self.logger.warning("%s process terminate() ignored: %s", side, e)

                try:
                    proc.join(timeout=1.0)
                    self.logger.info("%s Eyeloop process joined.", side)
                except AssertionError as e:
                    self.logger.warning("%s process join() skipped (not fully started?): %s",
                        side, e)
        except AssertionError as e:
            self.logger.warning("%s process is_alive() not valid (never started?): %s", side, e)
        finally:
            if side == "left":
                self.proc_left = None
                self.running_left = False
                if hasattr(self.eye_ready_s_l, "clear"):
                    self.eye_ready_s_l.clear()
                    self.first_frame_processed_s_l.clear()
                    self.logger.info("eye_ready_s_l cleared.")
            else:
                self.proc_right = None
                self.running_right = False
                if hasattr(self.eye_ready_s_r, "clear"):
                    self.eye_ready_s_r.clear()
                    self.first_frame_processed_s_r.clear()
                    self.logger.info("eye_ready_s_r cleared.")


    # ruff: noqa: F841
    # pylint: disable=unused-variable
    def _monitor_children(self) -> None:
        """Monitors the health of the Eyeloop processes."""

        if self.proc_left and self.running_left and not self.proc_left.is_alive():
            self.running_left = False
            self.last_error = "left process died"
            self.logger.error("Left EyeLoop process died.")

        if self.proc_right and self.running_right and not self.proc_right.is_alive():
            self.running_right = False
            self.last_error = "right process died"
            self.logger.error("Right EyeLoop process died.")

        if self.tracker_state == "running" and not (self.running_left and self.running_right):
            # degraded or stopped unexpectedly
            self.tracker_state = "error"


    def _drain_health_bus(self) -> None:
        """Drains the tracker health queue."""
        try:
            # Non-blocking-ish read from external queue
            payload = self.tracker_health_q.get(timeout=0.01)
            # TODO: handle payload (metrics / soft warnings etc.)
            # DOES NOT change is_online(); may update tracker_state/last_error if needed.
        except queue.Empty:
            pass
