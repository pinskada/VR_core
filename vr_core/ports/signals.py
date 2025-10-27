"""Siignals definitions."""

import threading
import multiprocessing


class ConfigSignals:
    """Configuration service signals."""

    def __init__(self) -> None:
        self.config_ready = threading.Event()  # set when initial config is loaded


class CommRouterSignals:
    """Shared memory signals for tracker-networking communication."""

    def __init__(self) -> None:
        self.tcp_send_enabled = threading.Event()   # external on/off switch
        self.frame_ready = threading.Event()        # producer sets when it wrote a new frame
        self.sync_frames = threading.Event()       # consumer sets the frame is processed
        self.shm_reconfig = threading.Event()       # signal to reconfigure shared memory


class TrackerSignals:
    """Control signals for tracker module"""

    def __init__(self) -> None:
        self.provide_frames = threading.Event()
        self.log_data = threading.Event()
        self.provide_data = threading.Event()
        self.start_tracker = threading.Event()
        self.stop_tracker = threading.Event()

class EyeReadySignals:
    """Signals indicating eye readiness for eye-tracking module"""

    def __init__(self) -> None:
        self.left_eye_ready = multiprocessing.Event()
        self.right_eye_ready = multiprocessing.Event()
