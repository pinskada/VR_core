from vr_core.network.tcp_server import TCPServer
from vr_core.raspberry_perif.esp32 import ESP32
from vr_core.raspberry_perif.gyroscope import Gyroscope
from vr_core.eye_tracker.tracker_center import TrackerCenter
import vr_core.module_list as ModuleList
from vr_core.health_monitor import HealthMonitor
from vr_core.network.command_dispatcher import CommandDispatcher

import vr_core.config as config

import time

class Core:
    """
    Core engine for RPI..
    """

    def __init__(self) -> None:
        
        config.tracker_config.use_test_video = True  # Use saved video instead of live camera

        TCPServer()
        time.sleep(1)
        HealthMonitor()
        time.sleep(1)
        Gyroscope(force_mock=True)
        time.sleep(1)
        ESP32(force_mock=True)
        time.sleep(1)
        
        TrackerCenter()
        time.sleep(1)
        cmd = CommandDispatcher()
        time.sleep(1)
        
        
        cmd.handle_message(
            {
                "category": "tracker_mode",
                "action": "setup_tracker_1",
                "params": {},
            }
        )

        #time.sleep(10)

        #ModuleList.queue_handler.update_eyeloop_autosearch(autosearch=True)   

        time.sleep(5)
        ModuleList.command_dispatcher.handle_message(
            {
                "category": "config",
                "action": "tracker_config crop_left",
                "params": ((0.0, 0.3), (0.0, 1.0))
            }
        )

if __name__ == "__main__":
    Core()