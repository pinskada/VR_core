# ruff: noqa: ERA001, ARG002, ANN401

"""Control service for eye-tracking module."""

from __future__ import annotations

import queue
from typing import TYPE_CHECKING, Any

from vr_core.base_service import BaseService
from vr_core.ports.interfaces import ITrackerControl, ITrackerService
from vr_core.utilities.logger_setup import setup_logger

if TYPE_CHECKING:
    import itertools
    import multiprocessing as mp

    from vr_core.config_service.config import Config
    from vr_core.ports.signals import CommRouterSignals, TrackerDataSignals, TrackerSignals


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

    def __init__(  # noqa: PLR0913
        self,
        com_router_queue_q: queue.PriorityQueue[Any],
        pq_counter: itertools.count[int],
        tracker_cmd_l_q: mp.Queue[Any],
        tracker_cmd_r_q: mp.Queue[Any],
        comm_router_signals: CommRouterSignals,
        tracker_data_signals: TrackerDataSignals,
        tracker_signals: TrackerSignals,
        i_tracker_process: ITrackerService,
        config: Config,
    ) -> None:
        """Initialize the TrackerControl service."""
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
        """Start the tracker module."""
        self.online = True
        self._ready.set()

        #self.logger.info("Service set ready.")


    def _run(self) -> None:
        """Run the main loop for the tracker control service."""
        while not self._stop.is_set():
            self._stop.wait(0.1)


    def _on_stop(self) -> None:
        """Stop the tracker module."""
        self.online = False
        #self._offline_mode()
        self._unsubscribe()
        #self.logger.info("Service stopped.")


# ---------- Public APIs ----------

    def tracker_control(
        self,
        msg: dict[str, Any],
    ) -> None:
        """Control the tracker module based on incoming messages."""
        cmd_type = msg.get("mode")

        match cmd_type:
            case "offline":
                self._offline_mode()
            case "online":
                self._online_mode()
            case "no_preview":
                self._tracker_preview_mode(preview_type="none")
                self._camera_preview_mode(send_preview=False)
            case "camera_preview":
                self._camera_preview_mode(send_preview=True)
            case "cr_preview":
                self._tracker_preview_mode(preview_type="cr")
            case "pupil_preview":
                self._tracker_preview_mode(preview_type="pupil")
            case _:
                self.logger.error("Unknown tracker control command: %s", cmd_type)


# ---------- Mode setters ----------

    def _offline_mode(self) -> None:
        """Set the tracker module to offline mode."""
        self.logger.info("Setting tracker to offline mode.")

        self._stop_all_actions()

        self.tracker_data_to_tcp_s.clear()
        self.tracker_data_to_gaze_s.clear()
        self.router_sync_frames_s.clear()
        self.tcp_shm_send_s.clear()


    def _camera_preview_mode(
        self,
        *,
        send_preview: bool,
    ) -> None:
        """Set the tracker module to camera preview mode."""
        self.logger.info("Setting tracker camera preview mode to %s.", send_preview)

        self._stop_all_actions()
        if send_preview:
            self.tcp_shm_send_s.set()
        else:
            self.tcp_shm_send_s.clear()


    def _tracker_preview_mode(
        self,
        preview_type: str,
    ) -> None:
        """Set the tracker module to eye-tracker preview mode."""
        self.logger.info("Setting tracker preview mode to %s.", preview_type)

        self.prompt_preview(
            preview_type=preview_type,
        )


    def _online_mode(self) -> None:
        """Set the tracker module to online mode."""
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
        # self.logger.info("providet_frame_s is set.")

        self.tracker_data_to_tcp_s.clear()
        self.tracker_data_to_gaze_s.set()
        self.router_sync_frames_s.clear()
        self.tcp_shm_send_s.clear()
        self._set_eyeloop_config()

# ---------- Helpers ----------

    def _stop_all_actions(self) -> None:
        """Stop all resources."""
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


    def _empty_cmd_queues(self) -> None:
        for q in (self.tracker_cmd_l_q, self.tracker_cmd_r_q):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:  # noqa: PERF203
                    break

    def prompt_preview(
        self,
        *,
        preview_type: str,
    ) -> None:
        """Update Eyeloop whether to send preview."""
        self.tracker_cmd_l_q.put(
        {
            "type": "config",
            "param": "preview",
            "value": preview_type,
        })
        self.tracker_cmd_r_q.put(
        {
            "type": "config",
            "param": "preview",
            "value": preview_type,
        })
        # self.logger.info("tracker_cmd_l_q: Prompted preview : %s", preview_type)


    # pylint: disable=unused-argument
    def _on_config_changed(
        self,
        path: str,
        old_val: Any,
        new_val: Any,
    ) -> None:
        """Handle configuration changes."""
        if self.tracker_running_l_s.is_set() or self.tracker_running_r_s.is_set():
            (_, field) = self._split_path(path, ".")
            if field == "":
                return
            self._send_config_to_eyeloop(field, new_val)
            # self.logger.info("tracker_cmd_l_q: Prompted config change for %s: %s", field, new_val)


    def _set_eyeloop_config(self) -> None:
        """Send the current configuration to both EyeLoop processes."""
        eyeloop_config = self.cfg.eyeloop.__dict__

        for field, value in eyeloop_config.items():
            self._send_config_to_eyeloop(field, value)
        # self.logger.info("Sent full eyeloop configuration to EyeLoop processes.")


    def _send_config_to_eyeloop(
        self,
        field: str,
        value: Any,
    ) -> None:
        """Send the current configuration to both EyeLoop processes."""
        if "left" in field:
            self.tracker_cmd_l_q.put(
            {
                "type": "config",
                "param": field.removeprefix("right_").removeprefix("left_"),
                "value": value,
            })
        elif "right" in field:
            self.tracker_cmd_r_q.put(
            {
                "type": "config",
                "param": field.removeprefix("right_").removeprefix("left_"),
                "value": value,
            })
        else:
            self.logger.error("Unknown configuration for field: %s", field)


    def _split_path(
        self,
        path: str,
        split_symbol: str,
    ) -> tuple[str, str]:
        """Split a dotted path with 2 strings into section and field."""
        parts = path.split(split_symbol)

        if len(parts) != 2:  # noqa: PLR2004
            self.logger.error("Message %s should have two parts.", path)
            return ("", "")

        section = parts[0]
        field = parts[1]

        return section, field
