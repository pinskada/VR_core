"""Control service for eye-tracking module."""

import queue
import multiprocessing as mp

from vr_core.base_service import BaseService


class TrackerControl(BaseService):
    """Tracker control service."""

    def __init__(
        self,
        com_router_queue_q: queue.PriorityQueue,
        tracker_cmd_l_q: mp.Queue,
        tracker_cmd_r_q: mp.Queue,
    ) -> None:

        super().__init__("TrackerControl")

        self.com_router_queue_q = com_router_queue_q
        self.tracker_cmd_l_q = tracker_cmd_l_q
        self.tracker_cmd_r_q = tracker_cmd_r_q


        self.online = False


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
