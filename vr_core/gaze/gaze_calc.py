import vr_core.module_list as module_list 
from vr_core.config import tracker_config
from vr_core.config import eye_processing_config
from vr_core.gaze.models import inverse_model
import time

class GazeCalc:
    def __init__(self):
        self.online = True # Flag to indicate if the system is online or offline

        module_list.main_processor = self

        self.health_monitor = module_list.health_monitor # Needed for health monitoring
        self.esp32 = module_list.esp32 # Needed for sending data to stepper motor
        self.tcp_server = module_list.tcp_server # Needed for sending data to the unity client

        self.print_model_error = False # Flag to indicate if the model error should be printed

        self.trust_tracker = True # Flag to indicate if the tracker is trusted or not based on gyroscope data

        self.trust_eye_data = [] # Indicates if the eye data is trusted or not based on gyroscope data

    def process_eye_data(self, ipd):
        """
        Process the eye data.
        """

        if eye_processing_config.model_params and eye_processing_config.corrected_model_params and self.print_model_error:
            self.health_monitor.failure("MainProcessor", "Model not loaded, cannot process eye data.")
            print("[WARN] MainProcessor: Model not loaded, cannot process eye data.")
            self.print_model_error = False
            return

        self.print_model_error = False

        self.model_real = eye_processing_config.model_params
        self.model_corrected = eye_processing_config.corrected_model_params


        distance_real = inverse_model.predict(ipd, self.model_real)
        distance_corrected = inverse_model.predict(ipd, self.model_corrected)

        if self.trust_tracker:
            try:
                self.tcp_server.send(distance_real, data_type='JSON', priority='medium') # Send the gaze distance to the Unity client
            except Exception as e:
                self.health_monitor.failure("MainProcessor", f"Error sending data to Unity: {e}")
                print(f"[ERROR] MainProcessor: Error sending data to Unity: {e}")

            try:
                self.esp32.send_gaze_distance(distance_corrected) # Send the gaze distance to the ESP32
            except Exception as e:
                self.health_monitor.failure("MainProcessor", f"Error sending data to ESP32: {e}")
                print(f"[ERROR] MainProcessor: Error sending data to ESP32: {e}")

    def gyro_handler(self, input_gyro_data):
        """
        Update trust based on gyroscope rotation speed.
        gyro_data: (x_rotation, y_rotation, z_rotation) in deg/s
        """
        x_rotation = input_gyro_data.get("x")
        y_rotation = input_gyro_data.get("y")
        z_rotation = input_gyro_data.get("z")

        total_rotation = (x_rotation**2 + y_rotation**2 + z_rotation**2)**0.5

        if total_rotation > self.gyro_threshold:
            self.trust_tracker = False
            print(f"[DEBUG] Gyro rotation speed: {total_rotation:.2f} deg/sec | Trust: {self.trust_tracker}")
        else:
            self.trust_tracker = True


    def is_online(self):
        return self.online


