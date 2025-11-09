"""Siignals definitions."""

from threading import Event
import multiprocessing as mp

class ConfigSignals:
    """Configuration service signals."""

    def __init__(self) -> None:
        self.config_ready_s = Event()  # set when initial config is loaded


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

        self.tcp_connected = Event()


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

        # Shared memory activity signal
        self.shm_active = mp.Event()
        self.shm_cleared = Event()

        self.first_frame_processed_l = Event()
        self.first_frame_processed_r = Event()

        # Info events about tracker state
        self.tracker_running_l = mp.Event()
        self.tracker_running_r = mp.Event()


        # Signals indicating processed eye frame
        self.eye_ready_l = mp.Event()
        self.eye_ready_r = mp.Event()


class EyeTrackerSignals:
    """Signals indicating eye readiness for Eyeloop module"""

    def __init__(self) -> None:
        # Signals indicating that shm has been closed
        self.tracker_shm_is_closed_l = mp.Event()   # signal that shared memory is closed
        self.tracker_shm_is_closed_r = mp.Event()   # signal that shared memory


class GazeSignals:
    """Signals for Gaze service."""

    def __init__(self) -> None:
        # Signal to indicate new gaze data is available
        self.gaze_calib_signal = Event()
        self.gaze_calc_signal = Event()
        self.ipd_to_tcp_signal = Event()
        self.gaze_to_tcp_signal = Event()
        self.calib_finalized_signal = Event()


class IMUSignals:
    """Signals for IMU service."""

    def __init__(self) -> None:
        # Signal to indicate new IMU data is available
        self.imu_send_over_tcp = Event()
        self.imu_send_to_gaze = Event()


class TestModeSignals:
    """Signals for test mode operation."""

    def __init__(self) -> None:
        # Signal to indicate test mode is active
        self.esp_mock_mode = Event()
        self.imu_mock_mode = Event()
        self.camera_mock_mode = Event()
