from network.tcp_server import TCPServer
from raspberry_perif.esp32 import ESP32
from raspberry_perif.gyroscope import Gyroscope
from vr_core.eye_tracker.tracker_launcher import TrackerHandler

import vr_core.config as config

class Core:
    """
    Core engine for RPI..
    """

    def __init__(self) -> None:
        
        config.TCPServer = TCPServer(self)
        tcp_server = config.TCPServer
        
        self.config = config
     