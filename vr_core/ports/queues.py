"""Centralized place to create/share queues/interfaces between services."""

from dataclasses import dataclass, field
from queue import PriorityQueue
import multiprocessing as mp
import queue
import itertools

@dataclass
class CommQueues:
    """
    Centralized place to create/share queues/interfaces between services.
    DI note: pass *only what you need* to each service; don’t share this whole object.
    """

    # Networking queues
    tcp_receive_q: queue.Queue = field(default_factory=queue.Queue)
    comm_router_q: PriorityQueue = field(default_factory=PriorityQueue)
    pq_counter = itertools.count()

    # Eye-tracker module queues
    tracker_cmd_l_q: mp.Queue = field(default_factory=mp.Queue)
    tracker_cmd_r_q: mp.Queue = field(default_factory=mp.Queue)

    tracker_resp_l_q: mp.Queue = field(default_factory=mp.Queue)
    tracker_resp_r_q: mp.Queue = field(default_factory=mp.Queue)

    tracker_health_q: queue.Queue = field(default_factory=queue.Queue)


    # Queue from sending computed tracker data from tracker module to gaze module
    tracker_data_q: queue.Queue = field(default_factory=queue.Queue)


    # Queue for sharing IPD data across Gaze module
    ipd_q: queue.Queue = field(default_factory=queue.Queue)


    # Peripheral device queues
    gyro_mag_q: queue.Queue = field(default_factory=queue.Queue)
    esp_cmd_q: queue.Queue = field(default_factory=queue.Queue)
