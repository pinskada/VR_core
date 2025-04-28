import vr_core.module_list as module_list 
from vr_core.config import tracker_config
from vr_core.config import eye_processing_config
from models import inverse_model
import time

class MainProcessor:
    def __init__(self):
        self.online = True # Flag to indicate if the system is online or offline

        module_list.main_processor = self

        self.health_monitor = module_list.health_monitor # Needed for health monitoring
        self.esp32 = module_list.esp32 # Needed for sending data to stepper motor
        self.tcp_server = module_list.tcp_server # Needed for sending data to the unity client

        self.print_model_error = False # Flag to indicate if the model error should be printed

        self.trust_tracker = True # Flag to indicate if the tracker is trusted or not based on gyroscope data

        self.trust_eye_data = [] # Indicates if the eye data is trusted or not based on gyroscope data

        self.gyro_buffer = []


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
        gyro_data: (x_rate, y_rate, z_rate) in deg/s
        """
        now = time.time()
        x = input_gyro_data.get('x')
        y = input_gyro_data.get('y')
        z = input_gyro_data.get('z')

        self.gyro_buffer.append((now, x, y, z))

        # Keep buffer size fixed
        if len(self.gyro_buffer) > self.buffer_size:
            self.gyro_buffer.pop(0)

        if len(self.gyro_buffer) < 2:
            # Not enough data to estimate speed yet
            return

        # Calculate angular speed
        t0, x0, y0, z0 = self.gyro_buffer[0]
        t1, x1, y1, z1 = self.gyro_buffer[-1]

        dt = t1 - t0
        if dt == 0:
            # Prevent division by zero
            return

        dx = x1 - x0
        dy = y1 - y0
        dz = z1 - z0

        total_rotation = sum(((dx)**2 + (dy)**2 + (dz)**2) ** 0.5)

        rotation_speed = total_rotation / dt

        if rotation_speed > self.gyro_threshold:
            self.trust_tracker = False
            print(f"[DEBUG] Gyro rotation speed: {rotation_speed:.2f} deg/sec | Trust: {self.trust_tracker}")
        else:
            self.trust_tracker = True


    def is_online(self):
        return self.online


