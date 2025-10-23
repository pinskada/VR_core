"""Centralized place to create/share queues/interfaces between services."""

from dataclasses import dataclass, field
from queue import PriorityQueue
import multiprocessing
import queue

@dataclass
class CommQueues:
    """
    Centralized place to create/share queues/interfaces between services.
    DI note: pass *only what you need* to each service; don’t share this whole object.
    """

    # Networking queues
    tcp_receive_q: queue.Queue = field(default_factory=queue.Queue)
    comm_router_q: PriorityQueue = field(default_factory=PriorityQueue)


    # Tracker module queues
    tracker_cmd_l_q: multiprocessing.Queue = field(default_factory=multiprocessing.Queue)
    tracker_cmd_r_q: multiprocessing.Queue = field(default_factory=multiprocessing.Queue)

    tracker_rsp_l_q: multiprocessing.Queue = field(default_factory=multiprocessing.Queue)
    tracker_rsp_r_q: multiprocessing.Queue = field(default_factory=multiprocessing.Queue)

    sync_q_l: multiprocessing.Queue = field(default_factory=multiprocessing.Queue)
    sync_q_r: multiprocessing.Queue = field(default_factory=multiprocessing.Queue)

    acknowledge_q_l: multiprocessing.Queue = field(default_factory=multiprocessing.Queue)
    acknowledge_q_r: multiprocessing.Queue = field(default_factory=multiprocessing.Queue)


    # Queue for sharing IPD data across Gaze module
    ipd_q: queue.Queue = field(default_factory=queue.Queue)


    # Queue from sending computed tracker data from tracker module to gaze module
    tracker_data_q: queue.Queue = field(default_factory=queue.Queue)


    # Peripheral device queues
    gyro_mag_q: queue.Queue = field(default_factory=queue.Queue)
    esp_cmd_q: queue.Queue = field(default_factory=queue.Queue)
