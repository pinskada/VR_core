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

        tcp_server = TCPServer()
        time.sleep(0.5)
        #HealthMonitor()
        time.sleep(0.5)
        Gyroscope()
        time.sleep(0.5)
        #ESP32(force_mock=True)
        time.sleep(0.5)
        #PreProcessor()
        time.sleep(0.5)
        #TrackerCenter()
        time.sleep(0.5)
        #CommandDispatcher()
       
if __name__ == "__main__":
    Core()