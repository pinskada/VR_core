from vr_core.eye_tracker.frame_provider import FrameProvider
from vr_core.eye_tracker.tracker_launcher import TrackerLauncher
from multiprocessing.shared_memory import SharedMemory
from vr_core.config import tracker_config
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
            
            self.setup_tracker_1()

        elif command == "setup_tracker_2":
            print("[INFO] TrackerCenter: Setup phase 2: Tracker started after preview configuration.")
            
            self.setup_tracker_2()

        elif command == "launch_tracker":
            print("[INFO] TrackerCenter: Tracker launched directly from config.")

            

    def setup_tracker_1(self):
        self.setup_mode = True
        try:
            self.tracker_launcher.stop()
        except:
            pass  # Ignore if tracker handler is not initialized

        self.stop_preview()  # In case a previous preview was running
        self.start_preview()  # Start the preview loop

    def setup_tracker_2(self):
        self.setup_mode = True
        self.stop_preview()

        self.queue_handler.send_command({"type": "preview"}, "L")
        self.queue_handler.send_command({"type": "preview"}, "R")

        self.frame_provider = FrameProvider() # Initialize frame provider
        self.tracker_launcher = TrackerLauncher() # Initialize EyeLoop process
        
        self.frame_provider_thread = threading.Thread(target=self.frame_provider.run(), daemon=True)
        self.frame_provider_thread.run() # Start the frame provider

    def launch_tracker(self):
        self.stop_preview()

        self.frame_provider = FrameProvider() # Initialize frame provider
        self.tracker_launcher = TrackerLauncher() # Initialize EyeLoop process
        
        self.frame_provider_thread = threading.Thread(target=self.frame_provider.run(), daemon=True)
        self.frame_provider_thread.run() # Start the frame provider
        self.queue_handler.update_eyeloop_autosearch(1) # Update the EyeLoop autosearch flag

    def start_preview(self):  

        self.frame_provider = FrameProvider()
        self.frame_provider_thread = threading.Thread(target=self.frame_provider.run(), daemon=True)
        self.frame_provider_thread.run() # Start the frame provider
        self.setup_mode = True
        self.preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self.preview_thread.start()
        print("[INFO] TrackerCenter: Preview streaming started via preview loop.")
        # Start preview loop externally or in separate thread/process

    def _preview_loop(self):
        self.frame_provider.run()  # Start the frame provider for preview
        channels = 1

        if not self.test_mode:
            try:
                shm_L = SharedMemory(name=tracker_config.sharedmem_name_left)
                shm_R = SharedMemory(name=tracker_config.sharedmem_name_right)
            except FileNotFoundError:
                self.health_monitor.failure("EyeTracker", "Shared memory not found for preview loop.")
                print("[ERROR] TrackerCenter: Shared memory not found for preview loop.")
                return

            while self.setup_mode:

                try:
                    img_L = np.ndarray(tracker_config.memory_shape_L, dtype=np.uint8, buffer=shm_L.buf).copy()
                    img_R = np.ndarray(tracker_config.memory_shape_R, dtype=np.uint8, buffer=shm_R.buf).copy()
                except Exception as e:
                    self.health_monitor.failure("EyeTracker", f"Shared memory read error: {e}")
                    print(f"[WARN] TrackerCenter: Shared memory read error: {e}")
                    continue
                
                try:
                    _, jpg_L = cv2.imencode(".jpg", img_L, [int(cv2.IMWRITE_JPEG_QUALITY), tracker_config.jpeg_quality])
                    _, jpg_R = cv2.imencode(".jpg", img_R, [int(cv2.IMWRITE_JPEG_QUALITY), tracker_config.jpeg_quality])
                except Exception as e:
                    self.health_monitor.failure("EyeTracker", f"JPEG encoding error: {e}")
                    print(f"[WARN] TrackerCenter: JPEG encoding error: {e}")
                    break
                
                self.tcp_server.send("left_JPEG", data_type='JSON', priority="medium")
                self.tcp_server.send(jpg_L.tobytes(), data_type='JPEG', priority="medium")

                self.tcp_server.send(payload="right_JPEG", data_type='JSON', priority="medium")
                self.tcp_server.send(jpg_R.tobytes(), data_type='JPEG', priority="medium")

                time.sleep(1 / tracker_config.preview_fps)
        else:
            while self.setup_mode:
                time.sleep(1 / tracker_config.preview_fps)
                print("[INFO] TrackerCenter: In test mode; pretending to write to a SharedMemory.")

    def stop_preview(self):
        self.setup_mode = False

        if hasattr(self, 'preview_thread') and self.preview_thread.is_alive():
            self.preview_thread.join()
            print("[INFO] TrackerCenter: Preview streaming stopped.")

        if self.frame_provider:
            self.frame_provider.stop()

        time.sleep(0.1)  # Allow time for the preview loop to stop
