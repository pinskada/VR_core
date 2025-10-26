"""Siignals definitions."""

import threading


class CommRouterSignals:
    """Shared memory signals for inter-thread communication."""

    def __init__(self) -> None:
        self.tcp_send_enabled = threading.Event()   # external on/off switch
        self.frame_ready = threading.Event()        # producer sets when it wrote a new frame
        self.shm_reconfig = threading.Event()       # signal to reconfigure shared memory

