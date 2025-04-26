import vr_core.module_list as module_list 
from vr_core.config import tracker_config

class Callibration:
    def __init__(self, eye_data):
        module_list.calibration_handler = self
        self.eye_data = eye_data
