from vr_core.eye_tracker.frame_provider import FrameProvider
from vr_core.eye_tracker.tracker_launcher import TrackerLauncher
from multiprocessing import shared_memory
from vr_core.config import TrackerConfig
from vr_core.config import CameraManagerConfig
from vr_core.eye_tracker.queue_handler import QueueHandler

import threading
import time
import numpy as np
import cv2
import vr_core.module_list as module_list 


class TrackerCenter:
    def __init__(self, test_mode=False):  # Initializes all tracking components and command queues
        self.online = True  # Flag to indicate if the tracker is online
        
        module_list.tracker_center = self  # Register the eye tracker centre in the module list
        self.tcp_server = module_list.tcp_server
        self.health_monitor = module_list.health_monitor

        self.test_mode = test_mode  # Flag to indicate if the module is in test mode
        self.setup_mode = False
        self.ready_to_track = False
        self.frame_provider = None
        self.tracker_launcher = None

        try:
            self.queue_handler = QueueHandler()  # Initialize the queue handler

            self.command_queue_L, self.command_queue_R = self.queue_handler.get_command_queues()
            self.response_queue_L, self.response_queue_R = self.queue_handler.get_response_queues()
            self.sync_queue_L, self.sync_queue_R = self.queue_handler.get_sync_queues()
        except Exception as e:
            self.online = False  # Set online status to False if initialization fails
            self.health_monitor.failure("EyeTracker", f"QueueHandler initialization error: {e}")
            print(f"[ERROR] TrackerCenter: QueueHandler initialization error: {e}")

    def is_online(self):
        """Check if the tracker is online."""
        return self.online

    def handle_command(self, command: str):
        if command == "setup_tracker_1":
            print("[INFO] TrackerCenter: Setup phase 1: Preview started.")

            self.setup_mode = True
            try:
                self.tracker_launcher.stop()
            except:
                pass  # Ignore if tracker handler is not initialized

            self.stop_preview()  # In case a previous preview was running
            self.start_preview()

        elif command == "setup_tracker_2":
            print("[INFO] TrackerCenter: Setup phase 2: Tracker started after preview configuration.")
            
            self.setup_mode = True
            self.stop_preview()

            self.queue_handler.send_command("track = 0", "L")
            self.queue_handler.send_command("track = 0", "R")

            self.frame_provider = FrameProvider(self.sync_queue_L, self.sync_queue_R) # Initialize frame provider
            self.tracker_launcher = TrackerLauncher()
            
            self.frame_provider.run() # Start the frame provider

        elif command == "launch_tracker":
            print("[INFO] TrackerCenter: Tracker launched directly from config.")

            self.stop_preview()
            self.ready_to_track = True

            self.queue_handler.send_command("track = 1", "L")
            self.queue_handler.send_command("track = 1", "R")

            self.frame_provider = FrameProvider(self.sync_queue_L, self.sync_queue_R) # Initialize frame provider
            self.tracker_launcher = TrackerLauncher()
            
            self.frame_provider.run() # Start the frame provider

    def start_preview(self):  

        self.frame_provider = FrameProvider(self.sync_queue_L, self.sync_queue_R)
        self.setup_mode = True
        self.preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self.preview_thread.start()
        print("[INFO] TrackerCenter: Preview streaming started via preview loop.")
        # Start preview loop externally or in separate thread/process

    def _preview_loop(self):
        self.frame_provider.run()  # Start the frame provider for preview
        shape = (CameraManagerConfig.height, CameraManagerConfig.width)
        channels = 3  # default to 3, can be dynamically detected later

        if not self.test_mode:
            try:
                shm_L = shared_memory.SharedMemory(name=TrackerConfig.sharedmem_name_left)
                shm_R = shared_memory.SharedMemory(name=TrackerConfig.sharedmem_name_right)
            except FileNotFoundError:
                self.health_monitor.failure("EyeTracker", "Shared memory not found for preview loop.")
                print("[ERROR] TrackerCenter: Shared memory not found for preview loop.")
                return

            while self.setup_mode:
                try:
                    img_L = np.ndarray(shape + (channels,), dtype=np.uint8, buffer=shm_L.buf).copy()
                    img_R = np.ndarray(shape + (channels,), dtype=np.uint8, buffer=shm_R.buf).copy()
                except Exception as e:
                    self.health_monitor.failure("EyeTracker", f"Shared memory read error: {e}")
                    print(f"[WARN] TrackerCenter: Shared memory read error: {e}")
                    continue
                
                try:
                    _, jpg_L = cv2.imencode(".jpg", img_L, [int(cv2.IMWRITE_JPEG_QUALITY), TrackerConfig.jpeg_quality])
                    _, jpg_R = cv2.imencode(".jpg", img_R, [int(cv2.IMWRITE_JPEG_QUALITY), TrackerConfig.jpeg_quality])
                except Exception as e:
                    self.health_monitor.failure("EyeTracker", f"JPEG encoding error: {e}")
                    print(f"[WARN] TrackerCenter: JPEG encoding error: {e}")
                    break
                
                self.tcp_server.send("left_JPEG", data_type='JSON', priority="medium")
                self.tcp_server.send(jpg_L.tobytes(), data_type='JPEG', priority="medium")

                self.tcp_server.send(message="right_JPEG", data_type='JSON', priority="medium")
                self.tcp_server.send(jpg_R.tobytes(), data_type='JPEG', priority="medium")

                time.sleep(1 / TrackerConfig.preview_fps)
        else:
            while self.setup_mode:
                time.sleep(1 / TrackerConfig.preview_fps)
                print("[INFO] TrackerCenter: In test mode; pretending to write to a SharedMemory.")


    def stop_preview(self):
        self.setup_mode = False

        if hasattr(self, 'preview_thread') and self.preview_thread.is_alive():
            self.preview_thread.join()
            print("[INFO] TrackerCenter: Preview streaming stopped.")

        if self.frame_provider:
            self.frame_provider.cleanup()

        time.sleep(0.1)  # Allow time for the preview loop to stop
