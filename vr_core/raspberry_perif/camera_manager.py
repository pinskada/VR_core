from vr_core.config import camera_manager_config
import vr_core.module_list as module_list 
import cv2

class CameraManager:
    def __init__(self):
        self.online = True  # Flag to indicate if the camera is online

        module_list.camera_manager = self # Register the camera manager in the module list
        self.command_dispatcher = module_list.command_dispatcher
        self.health_monitor = module_list.health_monitor

        try:
            from picamera2 import Picamera2 # type: ignore
            self.picam2 = Picamera2()  # Initialize camera object
        except ImportError as e:
            self.health_monitor.failure("CameraManager", f"Picamera2 not available: {e}")
            print(f"[ERROR] CameraManager: Picamera2 not available: {e}")
            self.online = False
            return
        
    def is_online(self):
        return self.online

    def apply_config(self):
        cam = camera_manager_config

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
        error = None
        for i in range(camera_manager_config.capture_retries):
            try:
                frame = self.picam2.capture()
                error = None
                break
            except Exception as e:
                error = e

        if error != None:
            self.health_monitor.failure("CameraManager", f"Capture error: {error}")
            print(f"[ERROR] CameraManager: Capture error: {error}")
            self.online = False
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return frame