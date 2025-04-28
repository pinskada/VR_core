import vr_core.module_list as module_list 
from vr_core.config import eye_processing_config
import numpy as np

class Calibration:
    def __init__(self, calib_points_num=3, diopter=0):
        self.online = True # Flag to indicate if the system is online or offline

        module_list.calibration_handler = self

        self.health_monitor = module_list.health_monitor # Needed for health monitoring
        self.tcp_server = module_list.tcp_server # Needed for sending data to the unity client

        self.diopter = diopter # Diopter value for the calibration
        self.distance = None # Placeholder for the distance of the virtual object
        self.collecting = False # Flag to indicate if the system is collecting data

        self.previous_distance = None  # Previous distance set by Unity
        self.current_distance = None  # Current gaze distance set by Unity
        self.samples_buffer = []  # Collected IPDs for the current distance
        self.calibration_data = {}  # Final dictionary: distance -> averaged IPD
        self.required_points = calib_points_num  # How many different distances expected
        self.completed_points = 0  # How many distances finished
        self.collecting = False  # Should we collect samples right now


    def get_ipd(self, relative_ipd):
        """
        Get the Interpupillary Distance (IPD) from the eye data.
        """
        
        if self.collecting and self.current_distance is not None:
            try:
                # Append the relative IPD to the samples buffer
                self.samples_buffer.append(relative_ipd)
            except Exception as e:
                self.health_monitor.failure("Calibration", f"Error appending IPD to buffer: {e}")
                print(f"[ERROR] Calibration: Error appending IPD to buffer: {e}")

    def get_current_distance(self, distance):
        """
        Get the current distance of the virtual object.
        """
        
        buffer = self.samples_buffer.copy()  # Buffer of samples collected for the previous distance
        self.previous_distance = self.current_distance  # Store the previous distance

        if self.previous_distance is not None:
            self.finalize_current_distance(buffer=buffer, distance=self.previous_distance)  # Finalize the previous distance if any

        self.current_distance = distance
        self.samples_buffer = []
        self.collecting = True
        print(f"[INFO] Calibration: Now collecting IPD samples for {distance} meters.")


    def finalize_current_distance(self, buffer, distance):
        """
        After collecting samples, finalize and store the averaged IPD for the current distance.
        """
        if len(buffer) == 0:
            print("[WARN] Calibration: No samples collected for distance.")
            return

        # --- Discard initial and final unstable samples ---
        trim_amount = max(1, int(eye_processing_config.crop_buffer_factor * len(buffer)))
        trimmed_samples = buffer[trim_amount:-trim_amount] if len(buffer) > 2 * trim_amount else buffer

        if len(trimmed_samples) == 0:
            print("[WARN] Calibration: Not enough valid samples after trimming.")
            return

        # --- Calculate stats ---
        mean_ipd = np.mean(trimmed_samples)
        std_ipd = np.std(trimmed_samples)

        print(f"[INFO] Calibration: Distance {distance} | Avg IPD = {mean_ipd:.6f} | Std Dev = {std_ipd:.6f}")

        # --- Validate sample quality ---
        if std_ipd > eye_processing_config.std_threshold:
            print(f"[WARN] Calibration: High standard deviation detected ({std_ipd:.6f}), suggesting retry.")
            self.tcp_server.send({"type": "calib", "status": "retry", "distance": distance}, data_type='JSON', priority='medium')
            self.collecting = False
            self.samples_buffer = []  # Collected IPDs for the current distance
            self.calibration_data = {}
            return

        # --- Save good sample ---
        self.calibration_data[distance] = mean_ipd
        self.completed_points += 1

        if self.completed_points >= self.required_points:
            # --- Calibration complete ---
            self.collecting = False
            self.fit_model()

        print(f"[INFO] Calibration: Finalized distance {distance} with averaged IPD.")


    def fit_model(self):
        """
        Fit the model to the eye data.
        """

        from models import inverse_model

        if len(self.calibration_data) < 2:
            print("[ERROR] Calibration: Not enough points to fit a model.")
            return None

        distances = np.array(list(self.calibration_data.keys()))
        ipds = np.array(list(self.calibration_data.values()))

        self.model_params = inverse_model.fit(distances, ipds)
        eye_processing_config.model_params = self.model_params

        print(f"[INFO] Calibration: Model fitted successfully: {self.model_params}")
        self.tcp_server.send({"type": "calib", "status": "success", "model_params": self.model_params}, data_type='JSON', priority='high')

        self.compensate_for_impairment()

    def compensate_for_impairment(self):
        """
        Compensate for users visual impairment.
        """
        model_params = eye_processing_config.model_params

        if self.diopter == 0.0:
            # No compensation needed
            eye_processing_config.corrected_model_params = (model_params[0], model_params[1])
            return

        # Calculate effective distance shift
        # How far would a perfect system see through user's optical correction
        # Focal length in meters
        focus_distance = 1.0 / self.diopter  # meters

        print(f"[INFO] Compensating for user diopter: {self.diopter} (focus at {focus_distance:.2f} m)")

        eye_processing_config.compensation_factor = 0.005 * self.diopter  # tweakable factor
        b_new = model_params[1] + eye_processing_config.compensation_factor  # shift the baseline slightly

        eye_processing_config.corrected_model_params = (model_params[0], b_new)  # Update the model parameters with the new 'b' value

    def is_online(self):
        return self.online
