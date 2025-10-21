"""Core engine for RPI."""

import os
import sys
import time
import multiprocessing
import queue
from dataclasses import dataclass

from vr_core.network.tcp_server import TCPServer
from vr_core.raspberry_perif.esp32 import ESP32
from vr_core.raspberry_perif.gyroscope import Gyroscope
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

@dataclass
class Queues:
    """
    Centralized place to create/share queues/interfaces between services.
    DI note: pass *only what you need* to each service; don’t share this whole object.
    """

    command_queue_l = multiprocessing.Queue()
    command_queue_r = multiprocessing.Queue()
    response_queue_l = multiprocessing.Queue()
    response_queue_r = multiprocessing.Queue()
    sync_queue_l = multiprocessing.Queue()
    sync_queue_r = multiprocessing.Queue()
    acknowledge_queue_l = multiprocessing.Queue()
    acknowledge_queue_r = multiprocessing.Queue()

    send_queue = queue.Queue()

class Core:
    """
    Core engine for RPI..
    """

    def __init__(self) -> None:
        print("Starting VR Core...")

        self.queues = Queues()

    def build(self):
        """Build and start all core modules."""

        tcp_server = TCPServer(
            config=config.tcp_config,
            send_q=self.queues.send_queue
        )



        config.tracker_config.use_test_video = True  # Use saved video instead of live camera
        if not config.tracker_config.use_test_video:
            module_list.cam_manager = CameraManager()
        time.sleep(0.5)
        HealthMonitor()
        time.sleep(0.5)
        Gyroscope()
        time.sleep(0.5)
        ESP32(force_mock=True)
        time.sleep(0.5)
        PreProcessor()
        time.sleep(0.5)
        CommandDispatcher()  # type: ignore # noqa: F841



if __name__ == "__main__":
    Core()
