from frame_provider import FrameProvider
from tracker_handler import TrackerHandler
from multiprocessing import shared_memory
from vr_core.config import EyeTrackerConfig
from vr_core.config import CameraConfig
from vr_core.eye_tracker.eyeloop_queue_handler import EyeLoopQueueHandler

import threading
import time
import numpy as np
import cv2
import vr_core.module_list as module_list 


class EyeTrackerCenter:
    def __init__(self):  # Initializes all tracking components and command queues
        module_list.eye_tracker_centre = self  # Register the eye tracker centre in the module list
        self.tcp_server = module_list.tcp_server

        self.setup_mode = False
        self.ready_to_track = False
        self.frame_provider = None
        self.tracker_handler = None

        self.eyeloop_queue_handler = EyeLoopQueueHandler()  # Initialize the queue handler

        self.command_queue_L, self.command_queue_R = self.eyeloop_queue_handler.get_command_queues()
        self.response_queue_L, self.response_queue_R = self.eyeloop_queue_handler.get_response_queues()
        self.sync_queue_L, self.sync_queue_R = self.eyeloop_queue_handler.get_sync_queues()

    def handle_command(self, command: str):
        if command == "setup_tracker_1":
            self.setup_mode = True
            try:
                self.tracker_handler.stop()
            except:
                pass  # Ignore if tracker handler is not initialized

            self.stop_preview()  # In case a previous preview was running
            self.start_preview()
            print("[INFO] Setup phase 1: Preview started.")

        elif command == "setup_tracker_2":
            self.setup_mode = True
            self.stop_preview()

            self.eyeloop_queue_handler.send_command("track = 0", "L")
            self.eyeloop_queue_handler.send_command("track = 0", "R")

            self.frame_provider = FrameProvider(self.sync_queue_L, self.sync_queue_R) # Initialize frame provider
            self.tracker_handler = TrackerHandler(self.frame_provider, self.command_queue_L, # Initialize tracker handler
            self.command_queue_R, self.response_queue_L, self.response_queue_R, self.sync_queue_L, self.sync_queue_R)
            
            self.frame_provider.run() # Start the frame provider
            print("[INFO] Setup phase 2: Tracker started after preview configuration.")

        elif command == "launch_tracker":
            self.stop_preview()
            self.ready_to_track = True

            self.eyeloop_queue_handler.send_command("track = 1", "L")
            self.eyeloop_queue_handler.send_command("track = 1", "R")

            self.frame_provider = FrameProvider(self.sync_queue_L, self.sync_queue_R) # Initialize frame provider
            self.tracker_handler = TrackerHandler(self.command_queue_L, # Initialize tracker handler
            self.command_queue_R, self.response_queue_L, self.response_queue_R, self.sync_queue_L, self.sync_queue_R)
            
            self.frame_provider.run() # Start the frame provider
            print("[INFO] Tracker launched directly from config.")

    def start_preview(self):  

        self.frame_provider = FrameProvider(self.sync_queue_L, self.sync_queue_R)
        self.setup_mode = True
        self.preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self.preview_thread.start()
        print("[INFO] Preview streaming started via preview loop.")
        # Start preview loop externally or in separate thread/process

    def _preview_loop(self):
        self.frame_provider.run()  # Start the frame provider for preview
        shape = (CameraConfig.height, CameraConfig.width)
        channels = 3  # default to 3, can be dynamically detected later

        try:
            shm_L = shared_memory.SharedMemory(name=EyeTrackerConfig.sharedmem_name_left)
            shm_R = shared_memory.SharedMemory(name=EyeTrackerConfig.sharedmem_name_right)
        except FileNotFoundError:
            print("[ERROR] Shared memory not found for preview loop.")
            return

        while self.setup_mode:
            try:
                img_L = np.ndarray(shape + (channels,), dtype=np.uint8, buffer=shm_L.buf).copy()
                img_R = np.ndarray(shape + (channels,), dtype=np.uint8, buffer=shm_R.buf).copy()
            except Exception as e:
                print(f"[WARN] Shared memory read error: {e}")
                continue

            _, jpg_L = cv2.imencode(".jpg", img_L, [int(cv2.IMWRITE_JPEG_QUALITY), EyeTrackerConfig.jpeg_quality])
            _, jpg_R = cv2.imencode(".jpg", img_R, [int(cv2.IMWRITE_JPEG_QUALITY), EyeTrackerConfig.jpeg_quality])

            self.tcp_server.send("left_JPEG", data_type='JSON', priority="medium")
            self.tcp_server.send(jpg_L.tobytes(), data_type='JPEG', priority="medium")

            self.tcp_server.send(message="right_JPEG", data_type='JSON', priority="medium")
            self.tcp_server.send(jpg_R.tobytes(), data_type='JPEG', priority="medium")

            time.sleep(1 / EyeTrackerConfig.preview_fps)

        print("[INFO] Preview streaming stopped.")


    def stop_preview(self):
        self.setup_mode = False
        
        if hasattr(self, 'preview_thread'):
            self.preview_thread.join()
        print("[INFO] Preview streaming stopped.")

        if self.frame_provider:
            self.frame_provider.cleanup()
