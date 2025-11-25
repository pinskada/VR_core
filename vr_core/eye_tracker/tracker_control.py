"""Control service for eye-tracking module."""

import itertools
import queue
import multiprocessing as mp
from typing import Any
from typing import Tuple

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.signals import CommRouterSignals, TrackerDataSignals, TrackerSignals
from vr_core.ports.interfaces import ITrackerService, ITrackerControl
from vr_core.utilities.logger_setup import setup_logger


class TrackerControl(BaseService, ITrackerControl):
    """Tracker control service.

    Controls starting/stopping the tracker module and handles incoming control messages.
    The tracker can work in the following modes:
        - Offline mode: the whole system is offline.
        - Camera preview mode: frames are forwarded to Unity but no eye-tracking is performed.
        - Eye-tracker preview mode: tracking is enabled and preview is forwarded (data+preprocess)
            to Unity.
        - Online mode: tracking is enabled and data is forwarded to the Gaze module and Unity
            (but no preview).
    """

    def __init__(
        self,
        com_router_queue_q: queue.PriorityQueue,
        pq_counter: itertools.count,
        tracker_cmd_l_q: mp.Queue,
        tracker_cmd_r_q: mp.Queue,
        comm_router_signals: CommRouterSignals,
        tracker_data_signals: TrackerDataSignals,
        tracker_signals: TrackerSignals,
        i_tracker_process: ITrackerService,
        config: Config
    ) -> None:

        super().__init__("TrackerControl")

        self.logger = setup_logger("TrackerControl")

        self.com_router_queue_q = com_router_queue_q
        self.pq_counter = pq_counter
        self.tracker_cmd_l_q = tracker_cmd_l_q
        self.tracker_cmd_r_q = tracker_cmd_r_q

        self.tcp_shm_send_s = comm_router_signals.tcp_shm_send_s
        self.router_sync_frames_s = comm_router_signals.router_sync_frames_s

        self.tracker_data_to_tcp_s = tracker_data_signals.tracker_data_to_tcp_s
        self.tracker_data_to_gaze_s = tracker_data_signals.tracker_data_to_gaze_s

        self.provide_frames_s = tracker_signals.provide_frames_s
        self.tracker_running_l_s = tracker_signals.tracker_running_l_s
        self.tracker_running_r_s = tracker_signals.tracker_running_r_s
        self.shm_cleared_s = tracker_signals.shm_cleared_s

        self.first_frame_processed_l_s = tracker_signals.first_frame_processed_l_s
        self.first_frame_processed_r_s = tracker_signals.first_frame_processed_r_s

        self.i_tracker_process = i_tracker_process

        self.cfg = config
        self._unsubscribe = config.subscribe("eyeloop", self._on_config_changed)

        self.online = False

        #self.logger.info("Service _ready is set.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """ Start the tracker module. """
        self.online = True
        self._ready.set()

        #self.logger.info("Service set ready.")


    def _run(self) -> None:
        """ Main loop for the tracker control service. """
        while not self._stop.is_set():
            self._stop.wait(0.1)


    def _on_stop(self) -> None:
        """ Stop the tracker module. """
        self.online = False
        #self._offline_mode()
        self._unsubscribe()
        #self.logger.info("Service stopped.")


# ---------- Public APIs ----------

    def tracker_control(self, msg: dict) -> None:
        """Control the tracker module based on incoming messages."""

        cmd_type = msg.get("mode")

        match cmd_type:
            case "offline":
                self._offline_mode()
            case "camera_preview":
                self._camera_preview_mode()
            case "tracker_preview":
                self._tracker_preview_mode()
            case "online":
                self._online_mode()
            case _:
                self.logger.error("Unknown tracker control command: %s", cmd_type)


# ---------- Mode setters ----------

    def _offline_mode(self) -> None:
        """Sets the tracker module to offline mode."""

        self.logger.info("Setting tracker to offline mode.")

        self._stop_all_actions()

        self.tracker_data_to_tcp_s.clear()
        self.tracker_data_to_gaze_s.clear()
        self.router_sync_frames_s.clear()
        self.tcp_shm_send_s.clear()


    def _camera_preview_mode(self) -> None:
        """Sets the tracker module to camera preview mode."""

        self.logger.info("Setting tracker to camera preview mode.")

        self._stop_all_actions()

        self.provide_frames_s.set()
        self.router_sync_frames_s.set()
        self.tracker_data_to_tcp_s.clear()
        self.tracker_data_to_gaze_s.clear()
        self.tcp_shm_send_s.set()


    def _tracker_preview_mode(self) -> None:
        """Sets the tracker module to eye-tracker preview mode."""

        self.logger.info("Setting tracker to eye-tracker preview mode.")

        self._stop_all_actions()

        self.i_tracker_process.start_tracker()

        if not (
            self.tracker_running_l_s.wait(self.cfg.tracker.eyeloop_start_timeout) and
            self.tracker_running_r_s.wait(self.cfg.tracker.eyeloop_start_timeout)
        ):
            self.logger.error("Processes have not started running.")
            return

        self.provide_frames_s.set()
        # self.logger.info("providet_frame_s is set.")

        self.tracker_data_to_tcp_s.set()
        self.tracker_data_to_gaze_s.clear()
        self.router_sync_frames_s.clear()
        self.tcp_shm_send_s.clear()

        self._setup_eyeloop(send_preview=True)


    def _online_mode(self) -> None:
        """Sets the tracker module to online mode."""

        self.logger.info("Setting tracker to online mode.")

        self._stop_all_actions()

        self.i_tracker_process.start_tracker()
        if not (
            self.tracker_running_l_s.wait(self.cfg.tracker.eyeloop_start_timeout) and
            self.tracker_running_r_s.wait(self.cfg.tracker.eyeloop_start_timeout)
        ):
            self.logger.error("Processes have not started running.")
            return

        self.provide_frames_s.set()
        self.logger.info("providet_frame_s is set.")

        self.tracker_data_to_tcp_s.clear()
        self.tracker_data_to_gaze_s.clear()
        self.router_sync_frames_s.clear()
        self.tcp_shm_send_s.clear()

        self._setup_eyeloop(send_preview=True)


# ---------- Helpers ----------

    def _stop_all_actions(self) -> None:
        """Stops all resources."""

        self.provide_frames_s.clear()
        if not self.shm_cleared_s.wait(5):
            self.logger.error("SHM has not been closed in time.")

        if (
            self.tracker_running_l_s.is_set() or
            self.tracker_running_r_s.is_set()
        ):
            self.i_tracker_process.stop_tracker()

        self.first_frame_processed_l_s.clear()
        self.first_frame_processed_r_s.clear()


        self._stop.wait(0.21)

        self._empty_cmd_queues()


    def _setup_eyeloop(
        self,
        send_preview: bool = False,
    ) -> None:
        # if (
        #     self.first_frame_processed_l_s.wait(10) and
        #     self.first_frame_processed_r_s.wait(10)
        # ):
        self._set_eyeloop_config()
        self.prompt_preview(send_preview)
        # self.logger.info("Sent config to Eyeloop.")


    def _empty_cmd_queues(self) -> None:
        for q in (self.tracker_cmd_l_q, self.tracker_cmd_r_q):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    def prompt_preview(self, send_preview: bool) -> None:
        """
        Updates Eyeloop whether to send preview.
        """

        self.tracker_cmd_l_q.put(
        {
            "type": "config",
            "param": "preview",
            "value": send_preview
        })
        self.tracker_cmd_r_q.put(
        {
            "type": "config",
            "param": "preview",
            "value": send_preview
        })
        # self.logger.info("tracker_cmd_l_q: Prompted preview : %s", send_preview)


    def update_eyeloop_autosearch(self, autosearch: bool) -> None:
        """
        Updates the EyeLoop process with the new autosearch configuration.
        """

        self.tracker_cmd_l_q.put(
        {
            "type": "config",
            "param": "auto_search",
            "value": autosearch
        })
        self.tracker_cmd_r_q.put(
        {
            "type": "config",
            "param": "auto_search",
            "value": autosearch
        })
        # self.logger.info("tracker_cmd_l_q: Prompted auto_search : %s", autosearch)


    # pylint: disable=unused-argument
    def _on_config_changed(self, path: str, old_val: Any, new_val: Any) -> None:
        """Handle configuration changes."""
        if self.tracker_running_l_s.is_set() or self.tracker_running_r_s.is_set():
            (_, field) = self._split_path(path, ".")
            if field == "":
                return
            self._send_config_to_eyeloop(field, new_val)
            # self.logger.info("tracker_cmd_l_q: Prompted config change for %s: %s", field, new_val)


    def _set_eyeloop_config(self) -> None:
        """Sends the current configuration to both EyeLoop processes."""
        eyeloop_config = self.cfg.eyeloop.__dict__

        for field, value in eyeloop_config.items():
            self._send_config_to_eyeloop(field, value)
        # self.logger.info("Sent full eyeloop configuration to EyeLoop processes.")


    def _send_config_to_eyeloop(
        self,
        field: str,
        value: Any
    ) -> None:
        """Sends the current configuration to both EyeLoop processes."""

        if "left" in field:
            self.tracker_cmd_l_q.put(
            {
                "type": "config",
                "param": field.removeprefix("right_").removeprefix("left_"),
                "value": value
            })
        elif "right" in field:
            self.tracker_cmd_r_q.put(
            {
                "type": "config",
                "param": field.removeprefix("right_").removeprefix("left_"),
                "value": value
            })
        else:
            self.logger.error("Unknown configuration for field: %s", field)


    def _split_path(self, path: str, split_symbol: str) -> Tuple[str, str]:
        """Splits a dotted path with 2 strings into section and field."""
        parts = path.split(split_symbol)

        if len(parts) != 2:
            self.logger.error("Message %s should have two parts.", path)
            return ("", "")

        section = parts[0]
        field = parts[1]

        return section, field
