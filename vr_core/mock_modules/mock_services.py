""" Mock scenarios for testing VR Core functionality without real hardware."""

from vr_core.config_service.config import Config
from vr_core.ports import signals
from vr_core.ports.queues import CommQueues
from vr_core.ports.interfaces import ITrackerService, ITrackerControl, INetworkService, IGazeService, IGazeControl, ICameraService
from vr_core.utilities.logger_setup import setup_logger

class MockServices:
    def __init__(
        self,
        config: Config,
        queues: CommQueues,
        config_signals: signals.ConfigSignals,
        comm_router_signals: signals.CommRouterSignals,
        tracker_data_signals: signals.TrackerDataSignals,
        tracker_signals: signals.TrackerSignals,
        eye_ready_signals: signals.EyeTrackerSignals,
        gaze_signals: signals.GazeSignals,
        imu_signals: signals.IMUSignals,
        test_signals: signals.TestModeSignals,
        i_tracker_process: ITrackerService,
        i_tracker_control: ITrackerControl,
        i_network_service: INetworkService,
        i_gaze_service: IGazeService,
        i_gaze_control: IGazeControl,
        i_camera_service: ICameraService,
    ) -> None:
        self.logger = setup_logger("MockServices")

        self.config = config
        self.queues = queues
        self.config_signals = config_signals
        self.comm_router_signals = comm_router_signals
        self.tracker_data_signals = tracker_data_signals
        self.tracker_signals = tracker_signals
        self.eye_ready_signals = eye_ready_signals
        self.gaze_signals = gaze_signals
        self.imu_signals = imu_signals
        self.test_signals = test_signals
        self.i_tracker_process = i_tracker_process
        self.i_tracker_control = i_tracker_control
        self.i_network_service = i_network_service
        self.i_gaze_service = i_gaze_service
        self.i_gaze_control = i_gaze_control
        self.i_camera_service = i_camera_service

