import numpy as np
import time
import cv2
import threading
from queue import Empty
from vr_core.config import tracker_config
from multiprocessing.shared_memory import SharedMemory
import vr_core.module_list as module_list 

class FrameProvider:  # Handles video acquisition, cropping, and shared memory distribution
    def __init__(self, test_mode=False):
        self.online = True

        module_list.frame_provider = self  # Register the frame provider in the module list
        self.health_monitor = module_list.health_monitor  # Health monitor instance
        self.use_test_video = tracker_config.use_test_video
        self.queue_handler = module_list.queue_handler  # Reference to the queue handler

        self.test_mode = test_mode  # Flag for test mode
        self.frame_id = 0  # Incremented with each new frame
        self.sync_queue_L, self.sync_queue_R = self.queue_handler.get_sync_queues()
        self.acknowledge_queue_L, self.acknowledge_queue_R = self.queue_handler.get_ack_queues()
        print(f"[INFO] FrameProvider: Frame id: {self.frame_id}.")
        # Choose between test video or live camera
        if self.use_test_video:
            self.cv2 = cv2
            self.cap = cv2.VideoCapture(tracker_config.test_video_path)
            self.health_monitor.status("FrameProvider", "Using test video for frame capture.")
            print("[INFO] FrameProvider: Using test video for frame capture.")
        else:
            module_list.cam_manager.apply_config()

        # Capture a test frame to determine actual crop size
        if self.use_test_video:
            ret, test_frame = self.cap.read()
            if not ret:
                self.health_monitor.failure("FrameProvider", "Failed to read test frame from video.")
                self.online = False
                raise RuntimeError("[ERROR] FrameProvider: Failed to read test frame from video.")
            test_frame = cv2.cvtColor(test_frame, cv2.COLOR_BGR2GRAY)

        else:
            test_frame = module_list.cam_manager.capture_frame()
        #test_frame = test_frame.transpose(1,0)[:, :]
        mean_img = np.mean(test_frame)

        self._allocate_memory(test_frame, crop_L_bool=True, crop_R_bool=True) # Allocate shared memory for left and right eye frames

    def run(self):
        try:
            while self.is_online():
                # Check if the frame provider is online
                # Increment frame ID for synchronization

                if self.frame_id != 0:
                    # Wait for both EyeLoop processes to acknowledge the previous frame
                    time.sleep(1 / tracker_config.frame_provider_max_fps)  # Maintain target FPS
                    self._wait_for_sync()

                self.frame_id += 1

                # Capture next frame from video or camera
                if self.use_test_video:
                    ret, full_frame = self.cap.read()
                    if full_frame is None:
                        print("[INFO] FrameProvider: End of video reached.")
                        return
                    full_frame = cv2.cvtColor(full_frame, cv2.COLOR_BGR2GRAY)

                    if not ret:
                        self.health_monitor.failure("FrameProvider", "Failed to read test frame from video or end of video.")
                        print("[INFO] FrameProvider: End of test video or read error.")
                        self.online = False
                        break
                else:
                    full_frame = module_list.cam_manager.capture_frame()

                if (self.frame_id) % 10 == 0:
                    #print(f"[INFO] FrameProvider: Frames being written to memory: {time.time()}")
                    pass
                #full_frame = full_frame.transpose(1,0)[:, :]

                # Conditions to check if crop dimensions or resolution have changed
                crop_L_bool = self.crop_L != tracker_config.crop_left
                crop_R_bool =  self.crop_R != tracker_config.crop_right
                res_bool = self.shape != full_frame.shape

                # If crop dimensions or resolution have changed, reallocate memory
                if crop_L_bool or crop_R_bool or res_bool:
                    print(f"[INFO] FrameProvider: Crop or resolution changed. Reallocating memory.")
                    self.health_monitor.status("FrameProvider", "Crop or resolution changed. Reallocating memory.")    
                    self._allocate_memory(full_frame, crop_L_bool, crop_R_bool)

                # Crop left and right regions from the full frame
                l = self._crop(full_frame, tracker_config.crop_left)
                r = self._crop(full_frame, tracker_config.crop_right)
            
                try:
                    # Write cropped frames to shared memory
                    np.ndarray(tracker_config.memory_shape_L, dtype=l.dtype, buffer=self.shm_L.buf)[:] = l
                    np.ndarray(tracker_config.memory_shape_R, dtype=r.dtype, buffer=self.shm_R.buf)[:] = r
                    #print(f"[INFO] FrameProvider: Wrote frame {self.frame_id} to shared memory.")
                except Exception as e:
                    self.health_monitor.failure("FrameProvider", f"Failed to write to shared memory: {e}")
                    print(f"[ERROR] FrameProvider: Failed to write to shared memory: {e}")
                    self.online = False
                    break

                try:
                    # Put frame ID in sync queues for both EyeLoop processes
                    self.sync_queue_L.put({"frame_id": self.frame_id, "type": "frame_id"})
                    self.sync_queue_R.put({"frame_id": self.frame_id, "type": "frame_id"})
                    #print(f"[INFO] FrameProvider: Put frame ID {self.frame_id} in sync queues.")
                except Exception as e:
                    self.health_monitor.failure("FrameProvider", f"Failed to put frame ID in sync queue: {e}")
                    print(f"[ERROR] FrameProvider: Failed to put frame ID in sync queue: {e}")
                    self.online = False
                    break


                if self.test_mode:
                    break # For testing purposes (running from test function), break after one frame
        finally:
            if not self.test_mode:
                self.stop()


    def _wait_for_sync(self):

        # Skip sync wait during tests
        if self.test_mode:
            return

        # Block until both EyeLoop processes confirm processing of current frame
        left_done = right_done = False
        start_time = time.time()
        #print(f"[INFO] FrameProvider: New frame: {self.frame_id}")
        while not (left_done and right_done):
            now = time.time()
            if now - start_time > tracker_config.sync_timeout:
                print(f"[WARN] FrameProvider: Timeout - total sync wait exceeded {tracker_config.sync_timeout} sec for frame {self.frame_id}")
                break

            try:
                if not left_done:
                    msg_L = self.acknowledge_queue_L.get(timeout=tracker_config.provider_queue_timeout)
                    if msg_L.get("type") == "ack" and msg_L.get("frame_id") == self.frame_id:
                        left_done = True
                        #print(f"[INFO] FrameProvider: Left EyeLoop acknowledged frame {self.frame_id}.")
            except Empty:
                pass

            try:
                if not right_done:
                    msg_R = self.acknowledge_queue_R.get(timeout=tracker_config.provider_queue_timeout)
                    if msg_R.get("type") == "ack" and msg_R.get("frame_id") == self.frame_id:
                        right_done = True
                        #print(f"[INFO] FrameProvider: Right EyeLoop acknowledged frame {self.frame_id}.")
            except Empty:
                pass

            time.sleep(0.001)  # Small sleep to avoid busy waiting

        if not left_done:
            print(f"[WARN] FrameProvider: Left EyeLoop did not acknowledge frame {self.frame_id} in time.")
        if not right_done:
            print(f"[WARN] FrameProvider: Right EyeLoop did not acknowledge frame {self.frame_id} in time.")


    def is_online(self):
        return self.online

    @property
    def currentframe_id(self):
        return self.frame_id


    def _allocate_memory(self, frame, crop_L_bool, crop_R_bool):

        #self.validate_crop()  # Validate crop dimensions
        frame_width, frame_height = frame.shape
        tracker_config.full_frame_resolution = frame.shape
        self.shape = frame.shape

        print(f"[INFO] FrameProvider: Current crop: {tracker_config.crop_left}, right: {tracker_config.crop_right}")

        if crop_L_bool:
            self.queue_handler.detach_eyeloop_memory("L")
            time.sleep(0.1)  # Small delay to ensure proper detachment

            self.crop_L = tracker_config.crop_left

            x_rel_start_L, x_rel_end_L = self.crop_L[0]
            y_rel_start_L, y_rel_end_L = self.crop_L[1]
            
            x_start_L = int(x_rel_start_L * frame_width)
            x_end_L = int(x_rel_end_L * frame_width)

            # Compute y coordinates based of the frame actual size
            y_start_L = int(y_rel_start_L * frame_height)
            y_end_L = int(y_rel_end_L * frame_height)
            
            tracker_config.memory_shape_L[0] = x_end_L-x_start_L
            tracker_config.memory_shape_L[1] = y_end_L-y_start_L

            self.memory_size_L = tracker_config.memory_shape_L[0] * tracker_config.memory_shape_L[1]


            self.clean_memory("L")  # Clean up left eye memory if it exists
            try:
                module_list.tracker_center.reset_preview_memory("L")
            except:
                pass

            try:
                self.shm_L = SharedMemory(name=tracker_config.sharedmem_name_left, create=True, size=self.memory_size_L)
            except Exception as e:
                self.health_monitor.failure("FrameProvider", f"Failed to allocate shared memory: {e}")
                self.online = False
                raise RuntimeError(f"[ERROR] FrameProvider: Failed to allocate shared memory: {e}")
            
            self.queue_handler.update_eyeloop_memory("L")
            self.health_monitor.status("FrameProvider", f"Reallocated shared memory for eye: L")

            print(f"[INFO] FrameProvider: Reallocated left SHM.")
            print(f"[INFO] FrameProvider: Left memoryShape: {tracker_config.memory_shape_L}")

        if crop_R_bool:
            self.queue_handler.detach_eyeloop_memory("R")
            time.sleep(0.1)  # Small delay to ensure proper detachment

            self.crop_R = tracker_config.crop_right

            x_rel_start_R, x_rel_end_R = self.crop_R[0]
            y_rel_start_R, y_rel_end_R = self.crop_R[1]

            x_start_R = int(x_rel_start_R * frame_width)
            x_end_R = int(x_rel_end_R * frame_width)

            # Compute y coordinates based of the frame actual size
            y_start_R = int(y_rel_start_R * frame_height)
            y_end_R = int(y_rel_end_R * frame_height)

            tracker_config.memory_shape_R[0] = x_end_R-x_start_R
            tracker_config.memory_shape_R[1] = y_end_R-y_start_R

            self.memory_size_R = tracker_config.memory_shape_R[0] * tracker_config.memory_shape_R[1]

            self.clean_memory("R")  # Clean up left eye memory if it exists

            try:
                module_list.tracker_center.reset_preview_memory("R")
            except:
                pass

            try:
                self.shm_R = SharedMemory(name=tracker_config.sharedmem_name_right, create=True, size=self.memory_size_R)
            except Exception as e:
                self.health_monitor.failure("FrameProvider", f"Failed to allocate shared memory: {e}")
                self.online = False
                raise RuntimeError(f"[ERROR] FrameProvider: Failed to allocate shared memory: {e}")
            
            self.queue_handler.update_eyeloop_memory("R")
            
            self.health_monitor.status("FrameProvider", f"Reallocated shared memory for eye: R")
            print(f"[INFO] FrameProvider: Reallocated right SHM.")
            print(f"[INFO] FrameProvider: Right memoryShape: {tracker_config.memory_shape_R}")


    def validate_crop(self):    
        (x0_L, x1_L), (y0_L, y1_L) = tracker_config.crop_left
        (x0_R, x1_R), (y0_R, y1_R) = tracker_config.crop_right

        if x0_L < 0 or x1_L > 0.5 or y0_L < 0 or y1_L > 1 or x0_L > x1_L or y0_L > y1_L:
            self.health_monitor.status("FrameProvider", f"Invalid crop dimensions for left eye: {tracker_config.crop_left}, resetting to default.")
            print(f"[WARN] FrameProvider: Invalid crop dimensions for left eye: {tracker_config.crop_left}, resetting to default.")
            tracker_config.crop_left = ((0, 0.5), (0, 1))

        if x0_R < 0.5 or x1_R > 1 or y0_R < 0 or y1_R > 1 or x0_R > x1_R or y0_R > y1_R:
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
        return frame[x_start:x_end, y_start:y_end]
    
    def clean_memory(self, side="both"):
        
        if side == "both" or side == "L":
            print("[INFO] FrameProvider: Cleaning up left FrameProvider resources.")
            try:
                self.shm_L = SharedMemory(name=tracker_config.sharedmem_name_left)
                self.shm_L.unlink()
                self.shm_L.close()
                try:
                    self.shm_L = None
                except:
                    pass
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"[WARNING] Forced memory cleanup error: {e}")
        
        
        if side == "both" or side == "R":
            print("[INFO] FrameProvider: Cleaning up right FrameProvider resources.")
            try:
                self.shm_R = SharedMemory(name=tracker_config.sharedmem_name_right)
                self.shm_R.unlink()
                self.shm_R.close()
                try:
                    self.shm_R = None
                except:
                    pass
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"[WARNING] Forced memory cleanup error: {e}")

    def stop(self):
        self.online = False
        self.clean_memory()

        if self.use_test_video:
            self.cap.release()
