"""Core engine for RPI."""

import os
import sys
import time

from vr_core.network.tcp_server import TCPServer
from vr_core.raspberry_perif.esp32 import ESP32
from vr_core.raspberry_perif.gyroscope import Gyroscope
from vr_core.eye_tracker.tracker_center import TrackerCenter  # pyright: ignore[reportUnusedImport] # noqa: F401
import vr_core.module_list as ModuleList  # pyright: ignore[reportUnusedImport] # noqa: F401
from vr_core.health_monitor import HealthMonitor
from vr_core.network.command_dispatcher import CommandDispatcher
from vr_core.eye_processing.pre_processor import PreProcessor
from vr_core.raspberry_perif.camera_manager import CameraManager
import vr_core.module_list as module_list
import vr_core.config as config


print("===== DEBUG INFO =====")
print("PYTHONPATH:", os.environ.get("PYTHONPATH"))
print("VIRTUAL_ENV:", os.environ.get("VIRTUAL_ENV"))
print("SYS PATH:", sys.path)
print("======================")

class Core:
    """
    Core engine for RPI..
    """

    def __init__(self) -> None:
        config.tracker_config.use_test_video = True  # Use saved video instead of live camera

        if not config.tracker_config.use_test_video:
            module_list.cam_manager = CameraManager()
        tcp_server = TCPServer()  # type: ignore # noqa: F841
        time.sleep(0.5)
        HealthMonitor()
        time.sleep(0.5)
        Gyroscope()
        time.sleep(0.5)
        ESP32(force_mock=True)
        time.sleep(0.5)
        PreProcessor()
        time.sleep(0.5)
        cmd = CommandDispatcher()  # type: ignore # noqa: F841


        """
        ModuleList.cmd_dispatcher_queue.put({
            "category": "tracker_mode",
            "action": "setup_tracker_2"
        })
        time.sleep(20)
        cmd.handle_message({
            "category": "tracker_mode",
            "action": "setup_tracker_2",
        })
        time.sleep(5)
        cmd.handle_message({
            "category": "config",
            "action": "tracker_config crop_left",
            "params": ((0.0, 0.25), (0.0, 1.0))
        })
        """

if __name__ == "__main__":
    Core()
