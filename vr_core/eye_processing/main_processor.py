import vr_core.module_list as module_list 
from vr_core.config import tracker_config

class MainProcessor:
    def __init__(self):
        self.online = True # Flag to indicate if the system is online or offline

        module_list.main_processor = self

        self.health_monitor = module_list.health_monitor # Needed for health monitoring
        self.esp32 = module_list.esp32 # Needed for sending data to stepper motor
        self.tcp_server = module_list.tcp_server # Needed for sending data to the unity client

        self.model = None # Flag to indicate if the model is loaded

        self.trust_eye_data = [] # Indicates if the eye data is trusted or not based on gyroscope data

        self.get_model() # Get the model for eye data processing


    def get_model(self):
        """
        Get the model for eye data processing.
        """

        # Placeholder for the actual model loading process

        loaded_model = [] # This would be replaced with the actual model loading code

        self.model = loaded_model # Set the flag to indicate that the model is loaded


    def process_eye_data(self, eye_data):
        """
        Process the eye data.
        """

        if not self.model:
            self.health_monitor.failure("MainProcessor", "Model not loaded, cannot process eye data.")
            print("[WARN] MainProcessor: Model not loaded, cannot process eye data.")
            return

        # Placeholder for the actual model processing

        gaze_distance = [] # This would be replaced with the actual model processing code

        self.esp32.send_gaze_distance(gaze_distance) # Send the gaze distance to the ESP32
        self.tcp_server.send(gaze_distance, data_type='JSON', priority='medium') # Send the gaze distance to the Unity client



    def gyro_handler(self, input_gyro_data):
        """
        Handle gyroscope data.
        """

        # Placeholder for the actual gyroscope data handling

        # self.trust_eye_data = # Update the trust eye data based on gyroscope data

        trust_factor = [] # This would be replaced with the actual trust factor calculation

        self.trust_eye_data = trust_factor

    def is_online(self):
        return self.online


