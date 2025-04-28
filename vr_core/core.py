from vr_core.network.tcp_server import TCPServer
from vr_core.raspberry_perif.esp32 import ESP32
from vr_core.raspberry_perif.gyroscope import Gyroscope
from vr_core.eye_tracker.tracker_center import TrackerCenter
import vr_core.module_list as ModuleList
from vr_core.health_monitor import HealthMonitor
from vr_core.network.command_dispatcher import CommandDispatcher
from vr_core.eye_processing.pre_processor import PreProcessor

import vr_core.config as config

import time

class Core:
    """
    Core engine for RPI..
    """

    def __init__(self) -> None:
        
        config.tracker_config.use_test_video = True  # Use saved video instead of live camera

        TCPServer()
        HealthMonitor()
        Gyroscope(force_mock=True)
        ESP32(force_mock=True)
        #PreProcessor()
        #TrackerCenter()
        #cmd = CommandDispatcher()
        
        
        """
        cmd.handle_message(
            {
                "category": "tracker_mode",
                "action": "launch_tracker",
                "params": {},
            }
        )
        time.sleep(2)
        ModuleList.command_dispatcher.handle_message(
            {
                "category": "config",
                "action": "tracker_config crop_left",
                "params": ((0.2, 0.5), (0.3, 0.7))
            }
        )
        ModuleList.command_dispatcher.handle_message(
            {
                "category": "config",
                "action": "tracker_config crop_left",
                "params": ((0.5, 0.8), (0.3, 0.7))
            }
        )
        """
if __name__ == "__main__":
    Core()