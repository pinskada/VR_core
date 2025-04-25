import numpy as np
import time
import cv2
import threading
from queue import Empty
from vr_core.config import tracker_config
from multiprocessing import shared_memory
import vr_core.module_list as module_list 

class FrameProvider:  # Handles video acquisition, cropping, and shared memory distribution
    def __init__(self):
        self.online = True

        module_list.frame_provider = self  # Register the frame provider in the module list
        self.health_monitor = module_list.health_monitor  # Health monitor instance
        self.use_test_video = tracker_config.use_test_video
        self.queue_handler = module_list.queue_handler  # Reference to the queue handler

        self._frame_id = 0  # Incremented with each new frame
        self.sync_queue_L, self.sync_queue_R = self.queue_handler.get_sync_queues()

        # Choose between test video or live camera
        if self.use_test_video:
            self.cv2 = cv2
            self.cap = cv2.VideoCapture(tracker_config.test_video_path)
            self.health_monitor.status("FrameProvider", "Using test video for frame capture.")
            print("[INFO] FrameProvider: Using test video for frame capture.")
        else:
            from vr_core.raspberry_perif.camera_manager import CameraManager
            self.cam_manager = CameraManager()
            self.cam_manager.apply_config()

        # Capture a test frame to determine actual crop size
        if self.use_test_video:
            ret, test_frame = self.cap.read()
            if not ret:
                self.health_monitor.failure("FrameProvider", "Failed to read test frame from video.")
                self.online = False
                raise RuntimeError("[ERROR] FrameProvider: Failed to read test frame from video.")
        else:
            test_frame = self.cam_manager.capture_frame()
        test_frame = cv2.cvtColor(test_frame, cv2.COLOR_BGR2GRAY)
        test_frame = test_frame.transpose(1,0)[:, :, np.newaxis]

        self._allocate_memory(test_frame, crop_L_bool=True, crop_R_bool=True) # Allocate shared memory for left and right eye frames

    def run(self):
        try:
            self.frame_provider_thread = threading.Thread(target=self.run, daemon=True)
            self.frame_provider_thread.start() # Start the frame provider

            while self.is_online():
                # Check if the frame provider is online

                # Capture next frame from video or camera
                if self.use_test_video:
                    ret, image = self.cap.read()
                    full_frame = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    full_frame = full_frame.transpose(1,0)[:, :, np.newaxis]
                    if not ret:
                        self.health_monitor.failure("FrameProvider", "Failed to read test frame from video or end of video.")
                        print("[INFO] FrameProvider: End of test video or read error.")
                        self.online = False
                        break
                else:
                    full_frame = self.cam_manager.capture_frame()

                # Conditions to check if crop dimensions or resolution have changed
                crop_L_bool = self.crop_L != tracker_config.crop_left
                crop_R_bool =  self.crop_R != tracker_config.crop_right
                res_bool = self.shape != full_frame.shape

                # If crop dimensions or resolution have changed, reallocate memory
                if crop_L_bool or crop_R_bool or res_bool:                   
                    self.clean_memory()
                    self._allocate_memory(full_frame, crop_L_bool, crop_R_bool)

                # Crop left and right regions from the full frame
                l = self._crop(full_frame, tracker_config.crop_left)
                r = self._crop(full_frame, tracker_config.crop_right)

                time.sleep(1 / tracker_config.frame_provider_max_fps)  # Maintain target FPS

                if self._frame_id != 0:
                    # Wait for both EyeLoop processes to acknowledge the previous frame
                    self._wait_for_sync()
    
                # Increment frame ID for synchronization
                self._frame_id += 1

                try:
                    # Put frame ID in sync queues for both EyeLoop processes
                    self.sync_queue_L.put({"frame_id": self._frame_id, "type": "frame_id"})
                    self.sync_queue_R.put({"frame_id": self._frame_id, "type": "frame_id"})
                except Exception as e:
                    self.health_monitor.failure("FrameProvider", f"Failed to put frame ID in sync queue: {e}")
                    print(f"[ERROR] FrameProvider: Failed to put frame ID in sync queue: {e}")
                    self.online = False
                    break

                try:
                    # Write cropped frames to shared memory
                    np.ndarray(tracker_config.memory_shape_L, dtype=l.dtype, buffer=self.shm_L.buf)[:] = l
                    np.ndarray(tracker_config.memory_shape_R, dtype=r.dtype, buffer=self.shm_R.buf)[:] = r
                except Exception as e:
                    self.health_monitor.failure("FrameProvider", f"Failed to write to shared memory: {e}")
                    print(f"[ERROR] FrameProvider: Failed to write to shared memory: {e}")
                    self.online = False
                    break


                if self.use_test_video:
                    break # For testing purposes (running from test function), break after one frame
        finally:
            if not self.use_test_video:
                self.cleanup()


    def _wait_for_sync(self):

        # Skip sync wait during tests
        if self.use_test_video:
            return

        # Block until both EyeLoop processes confirm processing of current frame
        left_done = right_done = False
        start_time = time.time()

        while not (left_done and right_done):
            now = time.time()
            if now - start_time > tracker_config.sync_timeout:
                print(f"[WARN] FrameProvider: Timeout - total sync wait exceeded {tracker_config.sync_timeout} sec for frame {self._frame_id}")
                break

            try:
                if not left_done:
                    msg_L = self.sync_queue_L.get(timeout=tracker_config.queue_timeout)
                    if msg_L.get("type") == "ack" and msg_L.get("frame_id") == self._frame_id:
                        left_done = True
            except Empty:
                pass

            try:
                if not right_done:
                    msg_R = self.sync_queue_R.get(timeout=tracker_config.queue_timeout)
                    if msg_R.get("type") == "ack" and msg_R.get("frame_id") == self._frame_id:
                        right_done = True
            except Empty:
                pass

            time.sleep(0.001)  # Small sleep to avoid busy waiting

        if not left_done:
            print(f"[WARN] FrameProvider: Left EyeLoop did not acknowledge frame {self._frame_id} in time.")
        if not right_done:
            print(f"[WARN] FrameProvider: Right EyeLoop did not acknowledge frame {self._frame_id} in time.")


    def is_online(self):
        return self.online

    @property
    def current_frame_id(self):
        return self._frame_id


    def _allocate_memory(self, frame, crop_L_bool, crop_R_bool):

        self.validate_crop()  # Validate crop dimensions
        frame_width, frame_height, frame_channels = frame.shape
        self.shape = frame.shape

        if crop_L_bool:
            self.clean_memory("L")  # Clean up left eye memory if it exists

            self.crop_L = tracker_config.crop_left

            self.x_rel_start_L, self.x_rel_end_L = self.crop_L[0]
            self.y_rel_start_L, self.y_rel_end_L = self.crop_L[1]

            tracker_config.memory_shape_L[0] = int((self.x_rel_end_L - self.x_rel_start_L) * frame_width)
            tracker_config.memory_shape_L[1] = int((self.y_rel_end_L - self.y_rel_start_L) * frame_height)

            tracker_config.memory_shape_L[2] = frame_channels

            self.memory_size_L = tracker_config.memory_shape_L[0] * tracker_config.memory_shape_L[1] * tracker_config.memory_shape_L[2]

            try:
                self.shm_L = shared_memory.SharedMemory(name=tracker_config.sharedmem_name_left, create=True, size=self.memory_size_L)
            except Exception as e:
                self.health_monitor.failure("FrameProvider", f"Failed to allocate shared memory: {e}")
                self.online = False
                raise RuntimeError(f"[ERROR] FrameProvider: Failed to allocate shared memory: {e}")
            
            self.queue_handler.update_eyeloop_memory("L")
            self.health_monitor.status("FrameProvider", f"Reallocated shared memory for eye: L")

            print(f"[INFO] FrameProvider: Reallocated left SHM.")


        if crop_R_bool:
            self.clean_memory("R")  # Clean up left eye memory if it exists

            self.crop_R = tracker_config.crop_right

            self.x_rel_start_R, self.x_rel_end_R = self.crop_R[0]
            self.y_rel_start_R, self.y_rel_end_R = self.crop_R[1]

            tracker_config.memory_shape_R[0] = int((self.x_rel_end_R - self.x_rel_start_R) * frame_width)
            tracker_config.memory_shape_R[1] = int((self.y_rel_end_R - self.y_rel_start_R) * frame_height)
            
            tracker_config.memory_shape_R[2] = frame_channels

            self.memory_size_R = tracker_config.memory_shape_R[0] * tracker_config.memory_shape_R[1] * tracker_config.memory_shape_R[2]

            try:
                self.shm_R = shared_memory.SharedMemory(name=tracker_config.sharedmem_name_right, create=True, size=self.memory_size_R)
                print(f"[INFO] FrameProvider: Reallocated SHM.")

            except Exception as e:
                self.health_monitor.failure("FrameProvider", f"Failed to allocate shared memory: {e}")
                self.online = False
                raise RuntimeError(f"[ERROR] FrameProvider: Failed to allocate shared memory: {e}")
            
            self.queue_handler.update_eyeloop_memory("R")
            self.health_monitor.status("FrameProvider", f"Reallocated shared memory for eye: R")
            print(f"[INFO] FrameProvider: Reallocated right SHM.")


    def validate_crop(self):    
        (x0_L, x1_L), (y0_L, y1_L) = tracker_config.crop_left
        (x0_R, x1_R), (y0_R, y1_R) = tracker_config.crop_right

        if x0_L < 0 or x1_L > 0.5 or y0_L < 0 or y1_L > 1:
            self.health_monitor.status("FrameProvider", f"Invalid crop dimensions for left eye: {tracker_config.crop_left}, resetting to default.")
            print(f"[WARN] FrameProvider: Invalid crop dimensions for left eye: {tracker_config.crop_left}, resetting to default.")
            tracker_config.crop_left = ((0, 0.5), (0, 1))

        if x0_R < 0.5 or x1_R > 1 or y0_R < 0 or y1_R > 1:
            self.health_monitor.status("FrameProvider", f"Invalid crop dimensions for right eye: {tracker_config.crop_right}, resetting to default.")
            print(f"[WARN] FrameProvider: Invalid crop dimensions for right eye: {tracker_config.crop_right}, resetting to default.")
            tracker_config.crop_right = ((0.5, 1), (0, 1))


    def _crop(self, frame, region):
        (x_rel_start, x_rel_end), (y_rel_start, y_rel_end) = region
        frame_width, frame_height = frame.shape[:2]

        # Compute x coordinates based of the frame actual size
        x_start = int(x_rel_start * frame_width)
        x_end = int(x_rel_end * frame_width)

        # Compute y coordinates based of the frame actual size
        y_start = int(y_rel_start * frame_height)
        y_end = int(y_rel_end * frame_height)

        # Extract ROI using crop coordinates
        return frame[y_start:y_end, x_start:x_end]
    
    def clean_memory(self, side="both"):
        print("[INFO] FrameProvider: Cleaning up FrameProvider resources.")
        
        if side == "both" or side == "L":
            try:
                existing_shm = shared_memory.SharedMemory(name=tracker_config.sharedmem_name_left)
                existing_shm.unlink()
                existing_shm.close()
            except FileNotFoundError:
                pass
        
        
        if side == "both" or side == "R":
            try:
                existing_shm = shared_memory.SharedMemory(name=tracker_config.sharedmem_name_right)
                existing_shm.unlink()
                existing_shm.close()
            except FileNotFoundError:
                pass

    def stop(self):
        if not self.online:
            self.online = False
            self.clean_memory()

            if self.use_test_video:
                self.cap.release()
