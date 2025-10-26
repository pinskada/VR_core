"""Gaze control and preprocessing module for VR Core on Raspberry Pi."""

import time
import numpy as np

import vr_core.module_list as module_list
from vr_core.config_service import config
from vr_core.gaze.gaze_calib import Calibration
from vr_core.gaze.gaze_calc import MainProcessor
from vr_core.ports.interfaces import IGazeService

class GazeControl(IGazeService):
    def __init__(self):
        self.online = True # Flag to indicate if the system is online or offline

        module_list.pre_processor = self

        self.health_monitor = module_list.health_monitor # Needed for health monitoring

        self.calibration = False # Flag to indicate if the system should send data to the calibration handler
        self.process = False # Flag to indicate if the system should send data to the main processor

        self.filtered_ipd = None # Placeholder for the filtered Interpupillary Distance (IPD) value

        self.print_ipd_state = 0 # Flag to indicate if the system should print the IPD state


    def gaze_control(self, msg) -> None:
        """
        Control the gaze module.
        """


    def get_relative_ipd(self, pupil_left, pupil_right):
        """
        Get relative ipd of the eye data.
        """

        # Extract pupil centers
        x_left, y_left = pupil_left['pupil'][0][0], pupil_left['pupil'][0][1]
        x_right, y_right = pupil_right['pupil'][0][0], pupil_right['pupil'][0][1]

        crop_left = tracker_config.crop_left  # Relative region (x1, x2, y1, y2) for the left eye, by default (0.0, 0.5), (0.0, 1.0)
        crop_right = tracker_config.crop_right  # Relative region (x1, x2, y1, y2) for the right eye, by default (0.5, 1.0), (0.0, 1.0)

        full_frame_width, full_frame_height = tracker_config.full_frame_resolution # Full frame resolution (height, width), likely 1920x1080

        # Calculate the full frame coordinates of the pupil centers
        full_x_left = crop_left[0][0] * full_frame_width + x_left
        full_y_left = crop_left[1][0] * full_frame_height + y_left

        full_x_right = crop_right[0][0] * full_frame_width + x_right
        full_y_right = crop_right[1][0] * full_frame_height + y_right

        # Calculate the Interpupillary Distance (IPD) in pixels
        ipd_px = np.linalg.norm([full_x_left - full_x_right, full_y_left - full_y_right])

        relative_ipd = ipd_px / full_frame_width # Normalize the IPD to the full frame width

        relative_ipd = self.filter_ipd(relative_ipd) # Apply filtering to the IPD value

        self.print_ipd_state += 1 # Increment the print IPD state counter

        # Print the IPD state if the flag is set
        if self.print_ipd_state == eye_processing_config.print_ipd_state:
            print(f"[INFO] PreProcessor: Relative IPD = {relative_ipd}")
            self.health_monitor.status("PreProcessor", f"Relative IPD = {relative_ipd}")
            self.print_ipd_state = 1

        if self.calibration == True and module_list.calibration_handler is not None:
            try:
                self.calibration.get_ipd(relative_ipd) # Get the IPD from the eye data
            except Exception as e:
                self.health_monitor.failure("PreProcessor", f"Attempted to get IPD, even though the CalibrationHandler is not initialised: {e}")
                print(f"[ERROR] PreProcessor: Attempted to get IPD, even though the CalibrationHandler is not initialised: {e}")

        elif self.process == True and module_list.main_processor is not None:
            try:
                module_list.main_processor.process_eye_data(relative_ipd)  # Process the eye data
            except Exception as e:
                self.health_monitor.failure("PreProcessor", f"Attempted to process eye data, even though the MainProcessor is not initialised: {e}")
                print(f"[ERROR] PreProcessor: Attempted to process eye data, even though the MainProcessor is not initialised: {e}")
        else:
            pass


    def filter_ipd(self, new_ipd):
        if self.filtered_ipd is None:
            # First value, no smoothing yet
            self.filtered_ipd = new_ipd
        else:
            self.filtered_ipd = eye_processing_config.filter_alpha * new_ipd + (1 - eye_processing_config.filter_alpha) * self.filtered_ipd
        return self.filtered_ipd


    def start_processing(self):
        """
        Start processing the eye data.
        """

        if self.process:
            print("[WARN] PreProcessor: Processing already started.")
            return
        self.health_monitor.status("PreProcessor", "Starting processing.")
        print("[INFO] PreProcessor: Starting processing.")
        module_list.main_processor = MainProcessor()
        self.process = True


    def stop_processing(self):
        """
        Stop processing the eye data.
        """

        self.health_monitor.status("PreProcessor", "Stopping processing.")
        print("[INFO] PreProcessor: Stopping processing.")
        module_list.main_processor = None
        self.process = False


    def start_calibration(self):
        """
        Start calibration of the eye data.
        """

        if self.calibration:
            print("[WARN] PreProcessor: Calibration already started.")
            return
        self.health_monitor.status("PreProcessor", "Starting calibration.")
        print("[INFO] PreProcessor: Starting calibration.")
        module_list.calibration_handler = Calibration()
        self.calibration = True


    def stop_calibration(self):
        """
        Stop calibration of the eye data.
        """

        self.health_monitor.status("PreProcessor", "Stopping calibration.")
        print("[INFO] PreProcessor: Stopping calibration.")
        module_list.calibration_handler = None
        self.calibration = False


    def is_online(self):
        return self.online
