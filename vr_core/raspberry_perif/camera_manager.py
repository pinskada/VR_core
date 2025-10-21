"""Camera manager for Raspberry Pi using Picamera2."""

import sys
#import time
import cv2

from vr_core.config import camera_manager_config
import vr_core.module_list as module_list

class CameraManager:
    """ Manages the Raspberry Pi camera using Picamera2."""
    def __init__(self):
        self.online = True  # Flag to indicate if the camera is online

        module_list.cam_manager = self # Register the camera manager in the module list
        self.command_dispatcher = module_list.command_dispatcher
        self.health_monitor = module_list.health_monitor
        self.frame_id = 0
        if not hasattr(sys, 'is_finalizing') or not sys.is_finalizing():
            try:
                from picamera2 import Picamera2 # type: ignore
                self.picam2 = Picamera2()  # Initialize camera object
            except Exception as e:
                if module_list.health_monitor:
                    module_list.health_monitor.failure("CameraManager",
                        f"Picamera2 not available: {e}"
                    )
                else:
                    print("[ERROR] CameraManager: HealthMonitor not available.")
                print(f"[ERROR] CameraManager: Picamera2 not available: {e}")
                self.online = False
                return
        else:
            print("[ERROR] CameraManager: Picamera2 not available, sys is finalizing.")

    def is_online(self):
        """ Check if the camera is online."""
        return self.online

    def start_camera(self):
        """ Start the camera with the configured settings."""
        try:
            self.apply_config()
            self.picam2.start()
            self.online = True
            print("[INFO] CamManager: Camera started.")
        except Exception as e:
            print(f"[ERROR] CamManager: Failed to start camera: {e}")
            self.online = False

    def stop_camera(self):
        """ Stop the camera."""
        try:
            self.picam2.stop()
            print("[INFO] CamManager: Camera stopped.")
            self.online = False
        except Exception as e:
            print(f"[ERROR] CamManager: Failed to stop camera: {e}")


    def apply_config(self):
        """ Apply camera configuration settings."""
        cam = camera_manager_config

        # Apply image resolution and buffer settings
        cfg = self.picam2.create_still_configuration(
            main={"size": (4608, 2592)},
            buffer_count=2
        )

        # try:
        #     self.picam2.configure(cfg)
        # except Exception as e:
        #     print(f"[ERROR] CamManager: Failed to configure camera: {e}")

        try:
            # Apply manual or automatic exposure and focus settings
            controls = {
                "AfMode": cam.af_mode,
                "LensPosition": int(cam.focus),
                "ExposureTime": int(cam.exposure_time),
                "AnalogueGain": cam.analogue_gain
            }
            self.picam2.set_controls(controls)
        except (AttributeError, TypeError, ValueError, OSError) as e:
            print(f"[ERROR] CamManager: Failed to set controls: {e}")

    def capture_frame(self):
        """ Capture a single frame from the camera."""
        self.frame_id += 1
        error = None

        for _ in range(camera_manager_config.capture_retries):
            try:
                # OR for async non-blocking
                request = self.picam2.capture_request()
                frame = request.make_array("main")
                request.release()

                frame = cv2.resize(frame, (int(camera_manager_config.width), int(camera_manager_config.height)), interpolation=cv2.INTER_LINEAR)

                error = None
                break
            except Exception as e:
                error = e
                print(f"[ERROR] CameraManager: error taking frame: {e}")

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


        if error is not None:
            if module_list.health_monitor:
                module_list.health_monitor.failure("CameraManager", f"Capture error: {error}")
            else:
                print("[ERROR] CameraManager: HealthMonitor not available.")
            print(f"[ERROR] CameraManager: Capture error: {error}")
            self.online = False
            return

        if self.frame_id % 10 == 0:
            #print(f"[INFO] CameraManager: Returning frame: {time.time()}")
            pass

        return frame
