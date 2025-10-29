"""Siignals definitions."""

from threading import Event
import multiprocessing as mp

class ConfigSignals:
    """Configuration service signals."""

    def __init__(self) -> None:
        self.config_ready = Event()  # set when initial config is loaded


class CommRouterSignals:
    """Shared memory signals for tracker-networking communication."""

    def __init__(self) -> None:
        # Enable/disable TCP sending of frames
        self.tcp_send_enabled = Event()
        # New frame is ready for CommRouter in shared memory
        self.frame_ready = Event()
        # Signal to CommRouter to sync frames, else just send latest
        self.sync_frames = Event()
        # Signal indicating that shm has been closed
        self.comm_shm_is_closed = Event()


class TrackerDataSignals:
    """Signals for tracker data sharing."""

    def __init__(self) -> None:
        # Control for TrackerComm to send data to network
        self.log_data = Event()
        # Control for TrackerComm to send data to gaze module
        self.provide_data = Event()


class TrackerSignals:
    """Control signals for tracker module"""

    def __init__(self) -> None:
        # Control for FrameProvider to start/stop providing frames
        self.provide_frames = Event()

        # Info events about tracker state
        self.tracker_running_l = Event()
        self.tracker_running_r = Event()

        # Shared memory activity signal
        self.shm_active = mp.Event()

        # Signals indicating processed eye frame
        self.eye_ready_l = mp.Event()
        self.eye_ready_r = mp.Event()

class EyeTrackerSignals:
    """Signals indicating eye readiness for Eyeloop module"""

    def __init__(self) -> None:
        # Signals indicating that shm has been closed
        self.tracker_shm_is_closed_l = mp.Event()   # signal that shared memory is closed
        self.tracker_shm_is_closed_r = mp.Event()   # signal that shared memory
