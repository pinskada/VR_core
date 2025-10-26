"""Routing table for message handling."""

from typing import Callable, Dict, Any
from queue import Queue

from vr_core.network.comm_contracts import MessageType
from vr_core.raspberry_perif.imu import Imu
from vr_core.gaze.gaze_control import GazeControl
from vr_core.eye_tracker.tracker_control import TrackerControl
from vr_core.config_service.config import Config

class RoutingTable:
    """Routing table for message handling."""

    def __init__(
        self,
        imu: Imu,
        gaze_control: GazeControl,
        tracker_control: TrackerControl,
        esp_cmd_q: Queue,
        config: Config
    ) -> None:
        self.esp_cmd_q = esp_cmd_q
        self.imu = imu
        self.gaze_control = gaze_control
        self.tracker_control = tracker_control
        self.config = config

        self.routing_table: Dict[MessageType, Callable[[Any], None]] = {
            MessageType.imuSensor: self.handle_imu_cmd,
            MessageType.gazeCalcControl: self.handle_gaze_control,
            MessageType.trackerControl: self.handle_tracker_control,
            MessageType.espConfig: self.handle_esp_config,
            MessageType.tcpConfig: self.handle_general_config,
        }

    #--- Handlers for different message types ---

    # TODO: implement a parser/validator for incoming messages
    def handle_imu_cmd(self, msg):
        """Handle IMU command message."""
        self.imu.imu_cmd(msg)
        print("Handling IMU command:", msg)


    # TODO: implement a parser/validator for incoming messages
    def handle_gaze_control(self, msg):
        """Handle gaze control message."""
        self.gaze_control.gaze_control(msg)
        print("Handling gaze control:", msg)


    # TODO: implement a parser/validator for incoming messages
    def handle_tracker_control(self, msg):
        """Handle tracker control message."""
        self.tracker_control.tracker_control(msg)
        print("Handling tracker control:", msg)


    # TODO: implement a parser/validator for incoming messages
    def handle_esp_config(self, msg):
        """Handle ESP config message."""
        self.esp_cmd_q.put(msg)
        print("Handling ESP config:", msg)


    # TODO: implement a parser/validator for incoming messages
    def handle_general_config(self, msg):
        """Handle general config message."""
        if not isinstance(msg, dict):
            print("[ConfigHandler] Expected dict, got:", type(msg))
            return

        # There should be exactly one key-value pair
        for path, value in msg.items():
            self.config.set(path, value)
            print(f"[ConfigHandler] Set {path} = {value}")
