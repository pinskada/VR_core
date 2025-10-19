"""Tracker Center Module for VR Eye Tracking System"""

from multiprocessing.shared_memory import SharedMemory
import threading
import time
import numpy as np
import cv2

import vr_core.module_list as module_list
from vr_core.eye_tracker.frame_provider import FrameProvider
from vr_core.eye_tracker.tracker_launcher import TrackerLauncher
from vr_core.config import tracker_config
from vr_core.eye_tracker.queue_handler import QueueHandler

class TrackerCenter:
    def __init__(self, test_mode=False):  # Initializes all tracking components and command queues
        self.online = True  # Flag to indicate if the tracker is online
        module_list.tracker_center = self  # Register the eye tracker centre in the module list
        self.tcp_server = module_list.tcp_server
        self.health_monitor = module_list.health_monitor

        self.test_mode = test_mode  # Flag to indicate if the module is in test mode
        self.setup_mode = False

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
        self.start_preview()  # Start the preview loop

    def setup_tracker_2(self):
        self.setup_mode = True

        module_list.queue_handler = QueueHandler()  # Reinitialize the queue handler
        time.sleep(0.1)  # Allow time for the queue handler to initialize

        module_list.frame_provider = FrameProvider() # Initialize frame provider

        self.frame_provider_thread = threading.Thread(target=module_list.frame_provider.run)
        self.frame_provider_thread.start() # Start the frame provider

        module_list.tracker_launcher = TrackerLauncher() # Initialize EyeLoop process
        module_list.queue_handler.update_eyeloop_autosearch(0) # Update the EyeLoop autosearch flag
        module_list.queue_handler.prompt_preview(1)

    def launch_tracker(self):
        module_list.queue_handler = QueueHandler()  # Reinitialize the queue handler
        time.sleep(0.1)  # Allow time for the queue handler to initialize

        module_list.frame_provider = FrameProvider() # Initialize frame provider
        
        self.frame_provider_thread = threading.Thread(target=module_list.frame_provider.run)
        self.frame_provider_thread.start() # Start the frame provider
        
        module_list.tracker_launcher = TrackerLauncher() # Initialize EyeLoop process
        module_list.queue_handler.update_eyeloop_autosearch(1) # Update the EyeLoop autosearch flag

    def start_preview(self):  
        module_list.queue_handler = QueueHandler()  # Reinitialize the queue handler
        time.sleep(0.1)  # Allow time for the queue handler to initialize

        module_list.frame_provider = FrameProvider()
        self.frame_provider_thread = threading.Thread(target=module_list.frame_provider.run)
        self.frame_provider_thread.start() # Start the frame provider
        self.setup_mode = True
        time.sleep(0.1)  # Allow time for the frame provider to start
        self.last_shape_L = tracker_config.memory_shape_L
        self.last_shape_R = tracker_config.memory_shape_R
        self.preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self.preview_thread.start()
        print("[INFO] TrackerCenter: Preview streaming started via preview loop.")
        # Start preview loop externally or in separate thread/process

    def _preview_loop(self):

        self.acknowledge_queue_L, self.acknowledge_queue_R = module_list.queue_handler.get_ack_queues()
        frame = 0
        if not self.test_mode:
            try:
                shm_L = SharedMemory(name=tracker_config.sharedmem_name_left)
                shm_R = SharedMemory(name=tracker_config.sharedmem_name_right)
            except FileNotFoundError:
                self.health_monitor.failure("EyeTracker", "Shared memory not found for preview loop.")
                print("[ERROR] TrackerCenter: Shared memory not found for preview loop.")
                return

            while self.setup_mode:
                frame += 1

                current_shape_L = tracker_config.memory_shape_L
                current_shape_R = tracker_config.memory_shape_R

                if self.reallocate_memory_L:
                    shm_L.close()  # Unlink the old shared memory
                    time.sleep(0.05)
                    shm_L = SharedMemory(name=tracker_config.sharedmem_name_left)  # Recreate the shared memory
                    time.sleep(0.05)
                    self.reallocate_memory_L = False  # Reset the reallocation flag
                    print(f"[INFO] FrameProvider: New left memory shape: {tracker_config.memory_shape_L}")
                    #print(f"[INFO] FrameProvider: Current left memory buffer: {shm_L.buf}")

                if self.reallocate_memory_R:
                    shm_R.close()  # Unlink the old shared memory
                    time.sleep(0.05)
                    shm_R = SharedMemory(name=tracker_config.sharedmem_name_right)  # Recreate the shared memory
                    time.sleep(0.05)
                    self.reallocate_memory_R = False  # Reset the reallocation flag
                    print(f"[INFO] FrameProvider: New right memory shape: {tracker_config.memory_shape_R}")
                    #print(f"[INFO] FrameProvider: Current right memory buffer: {shm_R.buf}")

                if frame % 1 == 0:
                    pass
                    #print(f"[INFO] TrackerCenter: Sending preview; Frame ID: {frame}.")
                try:
                    img_L = np.ndarray(tracker_config.memory_shape_L, dtype=np.uint8, buffer=shm_L.buf).copy()
                    img_R = np.ndarray(tracker_config.memory_shape_R, dtype=np.uint8, buffer=shm_R.buf).copy()
                    self.acknowledge_queue_L.put({"type": "ack", "frame_id": frame})
                    self.acknowledge_queue_R.put({"type": "ack", "frame_id": frame})
                    if frame % 10 == 0:
                        #print(f"[INFO] TrackerCenter: Frame load from memory {time.time()}")
                        pass
                except Exception as e:
                    self.health_monitor.failure("EyeTracker", f"Shared memory read error: {e}")
                    print(f"[WARN] TrackerCenter: Shared memory read error: {e}")
                    continue

                try:
                    _, jpg_L = cv2.imencode(".jpg", img_L, [int(cv2.IMWRITE_JPEG_QUALITY), int(tracker_config.jpeg_quality)])
                    _, jpg_R = cv2.imencode(".jpg", img_R, [int(cv2.IMWRITE_JPEG_QUALITY), int(tracker_config.jpeg_quality)])
                except Exception as e:
                    self.health_monitor.failure("EyeTracker", f"JPEG encoding error: {e}")
                    print(f"[WARN] TrackerCenter: JPEG encoding error: {e}")
                    break

                self.tcp_server.send({"type": "imageInfo", "data": "Left"}, data_type="JSON", priority="medium")
                time.sleep(0.1)
                self.tcp_server.send(jpg_L.tobytes(), data_type="JPEG", priority="medium")
                time.sleep(1 / tracker_config.preview_fps*2)

                self.tcp_server.send({"type": "imageInfo", "data": "Right"}, data_type="JSON", priority="medium")
                time.sleep(0.1)
                self.tcp_server.send(jpg_R.tobytes(), data_type="JPEG", priority="medium")
                time.sleep(1 / tracker_config.preview_fps*2)
                if frame % 10 == 0:
                    print(f"[INFO] TrackerCenter: Frame pending to unity {time.time()}")
                    #pass
        else:
            while self.setup_mode:
                frame += 1
                if frame % 10 == 0:
                    print(f"[INFO] TrackerCenter: In test mode; Frame ID: {frame}.")

                time.sleep(1 / tracker_config.preview_fps)
                print("[INFO] TrackerCenter: In test mode; pretending to write to a SharedMemory.")

    def reset_preview_memory(self, side):
        if side == "L":
            self.reallocate_memory_L = True
        elif side == "R":
            self.reallocate_memory_R = True
        else:
            raise ValueError("Invalid side. Use 'L' or 'R'.")

    def stop_preview(self):
        self.setup_mode = False
        try:
            module_list.queue_handler.close_eyeloop()
        except:
            pass

        time.sleep(0.5)

        try:
            module_list.frame_provider.stop()  # Stop the frame provider
            self.frame_provider_thread.join()  # Wait for the thread to finish
            module_list.frame_provider = None  # Clear the frame provider
        except:
            pass

        try:
            if self.preview_thread:
                self.preview_thread.join()  # Wait for the thread to finish
        except:
            pass
    
        time.sleep(0.1)  # Allow time for the preview loop to stop
