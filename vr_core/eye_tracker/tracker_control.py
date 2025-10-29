"""Control service for eye-tracking module."""

import queue
import multiprocessing as mp

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.signals import CommRouterSignals, TrackerDataSignals, TrackerSignals
from vr_core.ports.interfaces import ITrackerService


class TrackerControl(BaseService, ITrackerService):
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
        tracker_cmd_l_q: mp.Queue,
        tracker_cmd_r_q: mp.Queue,
        comm_router_signals: CommRouterSignals,
        tracker_data_signals: TrackerDataSignals,
        tracker_signals: TrackerSignals,
        config: Config
    ) -> None:

        super().__init__("TrackerControl")

        self.com_router_queue_q = com_router_queue_q
        self.tracker_cmd_l_q = tracker_cmd_l_q
        self.tracker_cmd_r_q = tracker_cmd_r_q

        self.tcp_send_enabled_s = comm_router_signals.tcp_send_enabled
        self.sync_frames_s = comm_router_signals.sync_frames

        self.log_data_s = tracker_data_signals.log_data
        self.provide_data_s = tracker_data_signals.provide_data

        self.provide_frames_s = tracker_signals.provide_frames
        self.tracker_running_l_s = tracker_signals.tracker_running_l
        self.tracker_running_r_s = tracker_signals.tracker_running_r

        self.cfg = config

        self.online = False


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """ Start the tracker module. """
        self.online = True
        self._ready.set()


    def _run(self) -> None:
        """ Main loop for the tracker control service. """
        while not self._stop.is_set():
            self._stop.wait(0.1)


    def _on_stop(self) -> None:
        """ Stop the tracker module. """
        self.online = False


# ---------- Public APIs ----------

    def tracker_control(self, msg: dict) -> None:
        """Control the tracker module based on incoming messages."""

        cmd_type = msg.get("mode")

        match cmd_type:
            case "offline":
                pass
            case "camera_preview":
                pass
            case "tracker_preview":
                pass
            case "online":
                pass
            case _:
                print(f"Unknown tracker control command: {cmd_type}")


# ---------- Mode setters ----------

    def _set_offline_mode(self) -> None:
        """Sets the tracker module to offline mode."""
        self.provide_frames_s.clear()
        self.stop_tracker()
        self.log_data_s.clear()
        self.provide_data_s.clear()
        self.sync_frames_s.clear()
        self.tcp_send_enabled_s.clear()


    def _camera_preview_mode(self) -> None:
        """Sets the tracker module to camera preview mode."""
        self.provide_frames_s.set()
        self.sync_frames_s.set()
        self.stop_tracker()
        self.log_data_s.set()
        self.provide_data_s.clear()
        self.tcp_send_enabled_s.set()


    def _tracker_preview_mode(self) -> None:
        """Sets the tracker module to eye-tracker preview mode."""
        self.provide_frames_s.set()
        self.start_tracker(test_mode=True)
        self.log_data_s.set()
        self.provide_data_s.clear()
        self.sync_frames_s.clear()
        self.tcp_send_enabled_s.clear()

        if (self.tracker_running_l_s.wait(self.cfg.tracker.sync_timeout) and
            self.tracker_running_r_s.wait(self.cfg.tracker.sync_timeout)):
            self.prompt_preview(True)


    def _online_mode(self) -> None:
        """Sets the tracker module to online mode."""
        self.provide_frames_s.set()
        self.start_tracker(test_mode=False)
        self.log_data_s.set()
        self.provide_data_s.set()
        self.sync_frames_s.clear()
        self.tcp_send_enabled_s.clear()

        if (self.tracker_running_l_s.wait(self.cfg.tracker.sync_timeout) and
            self.tracker_running_r_s.wait(self.cfg.tracker.sync_timeout)):
            self.prompt_preview(False)


# ---------- Helpers ----------

    def prompt_preview(self, send_preview):
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


    def update_eyeloop_autosearch(self, autosearch):
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
