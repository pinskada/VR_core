from vr_core.config import CameraConfig

try:
    from picamera2 import Picamera2 # type: ignore
except ImportError:
    raise ImportError("Picamera2 library is not installed. Please install it to use this module.")

class CameraConfigManager:
    def __init__(self, command_dispatcher):
        self.picam2 = Picamera2()  # Initialize camera object
        self.command_dispatcher = command_dispatcher

        self.command_dispatcher.camera_config_manager = self  # Set the command dispatcher to this instance

    def apply_config(self):
        cam = CameraConfig()

        # Apply image resolution and buffer settings
        cfg = self.picam2.create_still_configuration(
            main={"size": (cam.width, cam.height)},
            buffer_count=2
        )
        self.picam2.configure(cfg)

        # Apply manual or automatic exposure and focus settings
        self.picam2.set_controls({
            "AfMode": cam.af_mode,
            "LensPosition": cam.focus,
            "ExposureTime": cam.exposure_time,
            "AnalogueGain": cam.analogue_gain
        })
        self.picam2.start()  # Start the camera stream

    def capture_frame(self):
        return self.picam2.capture_array()  # Capture a frame as numpy array