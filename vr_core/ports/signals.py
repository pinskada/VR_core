"""Siignals definitions."""

import multiprocessing as mp
from threading import Event


class ConfigSignals:
    """Configuration service signals."""

    def __init__(self) -> None:
        self.config_ready_s = Event()  # set when initial config is loaded


class CommRouterSignals:
    """Shared memory signals for tracker-networking communication."""

    def __init__(self) -> None:
        # Enable/disable TCP sending of frames
        self.tcp_shm_send_s = Event()
        # New frame is ready for CommRouter in shared memory
        self.router_frame_ready_s = Event()
        # Signal to CommRouter to sync frames, else just send latest
        self.router_sync_frames_s = Event()
        # Signal indicating that shm has been closed
        self.router_shm_is_closed_s = Event()

        self.tcp_client_connected_s = Event()

        self.tracker_data_processed_s = Event()


class TrackerDataSignals:
    """Signals for tracker data sharing."""

    def __init__(self) -> None:
        # Control for TrackerComm to send data to network
        self.tracker_data_to_tcp_s = Event()
        # Control for TrackerComm to send data to gaze module
        self.tracker_data_to_gaze_s = Event()


class TrackerSignals:
    """Control signals for tracker module"""

    def __init__(self) -> None:
        # Control for FrameProvider to start/stop providing frames
        self.provide_frames_s = Event()

        # Shared memory activity signal
        self.shm_active_s = mp.Event()
        self.shm_cleared_s = Event()

        self.first_frame_processed_l_s = Event()
        self.first_frame_processed_r_s = Event()

        # Info events about tracker state
        self.tracker_running_l_s = mp.Event()
        self.tracker_running_r_s = mp.Event()

        # Signals indicating processed eye frame
        self.eye_ready_l_s = mp.Event()
        self.eye_ready_r_s = mp.Event()


class EyeTrackerSignals:
    """Signals indicating eye readiness for Eyeloop module"""

    def __init__(self) -> None:
        # Signals indicating that shm has been closed
        self.tracker_shm_is_closed_l_s = mp.Event()   # signal that shared memory is closed
        self.tracker_shm_is_closed_r_s = mp.Event()   # signal that shared memory


class GazeSignals:
    """Signals for Gaze service."""

    def __init__(self) -> None:
        # Signal to indicate new gaze data is available
        self.gaze_calib_s = Event()
        self.gaze_calc_s = Event()
        self.ipd_to_tcp_s = Event()
        self.gaze_to_tcp_s = Event()
        self.calib_finalized_s = Event()
        self.eyevectors_to_tcp_s = Event()


class IMUSignals:
    """Signals for IMU service."""

    def __init__(self) -> None:
        # Signal to indicate new IMU data is available
        self.imu_send_over_tcp_s = Event()
        self.imu_send_to_gaze_s = Event()
        self.hold_imu_during_calib_s = Event()


class TestModeSignals:
    """Signals for test mode operation."""

    def __init__(self) -> None:
        # Signal to indicate test mode is active
        self.esp_mock_mode_s = Event()
        self.imu_mock_mode_s = Event()
        self.camera_mock_mode_s = Event()
