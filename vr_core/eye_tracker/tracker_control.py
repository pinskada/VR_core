"""Control service for eye-tracking module."""

import queue

from vr_core.base_service import BaseService


class TrackerControl(BaseService):
    """Tracker control service."""

    def __init__(
        self,
        com_router_queue_q: queue.Queue
        ):

        super().__init__("TrackerControl")

        self.com_router_queue_q = com_router_queue_q
