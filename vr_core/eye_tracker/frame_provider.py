"""Frame Provider Module"""

import time
from queue import Empty
from multiprocessing.shared_memory import SharedMemory
import numpy as np
import cv2
#import threading

from vr_core.config import tracker_config
import vr_core.module_list as module_list


class FrameProvider:
    """Handles video acquisition, cropping, and shared memory distribution"""
    def __init__(self, test_mode=False):
        self.online = True
        self.shm_l = None
        self.shm_r = None

        module_list.frame_provider = self  # Register the frame provider in the module list
        self.use_test_video = tracker_config.use_test_video

        self.test_mode = test_mode  # Flag for test mode
        self.frame_id = 0  # Incremented with each new frame
        if module_list.queue_handler:
            self.sync_queue_l, self.sync_queue_r = module_list.queue_handler.get_sync_queues()
            self.acknowledge_queue_l, self.acknowledge_queue_r = module_list.queue_handler.get_ack_queues()

        # Choose between test video or live camera
        if self.use_test_video:
            self.cv2 = cv2
            self.cap = cv2.VideoCapture(tracker_config.test_video_path)
            if module_list.health_monitor:
                module_list.health_monitor.status(
                    "FrameProvider",
                    "Using test video for frame capture."
                )
            print("[INFO] FrameProvider: Using test video for frame capture.")
        else:
            if module_list.cam_manager:
                module_list.cam_manager.apply_config()

        # Capture a test frame to determine actual crop size
        if self.use_test_video:
            ret, test_frame = self.cap.read()
            if not ret:
                if module_list.health_monitor:
                    module_list.health_monitor.failure(
                        "FrameProvider",
                        "Failed to read test frame from video."
                    )
                self.online = False
                raise RuntimeError("[ERROR] FrameProvider: Failed to read test frame from video.")
            test_frame = cv2.cvtColor(test_frame, cv2.COLOR_BGR2GRAY)

        else:
            if module_list.cam_manager:
                test_frame = module_list.cam_manager.capture_frame()
        #test_frame = test_frame.transpose(1,0)[:, :]
        mean_img = np.mean(test_frame)

        # Allocate shared memory for left and right eye frames
        self._allocate_memory(test_frame, crop_l_bool=True, crop_r_bool=True)

    def run(self):
        """Main loop for capturing and distributing frames."""
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
                        if module_list.health_monitor:
                            module_list.health_monitor.failure(
                            "FrameProvider",
                            "Failed to read test frame from video or end of video."
                        )
                        print("[INFO] FrameProvider: End of test video or read error.")
                        self.online = False
                        break
                else:
                    if module_list.cam_manager:
                        full_frame = module_list.cam_manager.capture_frame()

                if (self.frame_id) % 10 == 0:
                    #print(f"[INFO] FrameProvider: Frames being written to memory: {time.time()}")
                    pass

                # Conditions to check if crop dimensions or resolution have changed
                crop_l_bool = self.crop_l != tracker_config.crop_left
                crop_r_bool =  self.crop_r != tracker_config.crop_right
                res_bool = self.shape != full_frame.shape

                # If crop dimensions or resolution have changed, reallocate memory
                if crop_l_bool or crop_r_bool or res_bool:
                    print("[INFO] FrameProvider: Crop or resolution changed. Reallocating memory.")
                    if module_list.health_monitor:
                        module_list.health_monitor.status(
                            "FrameProvider",
                            "Crop or resolution changed. Reallocating memory."
                        )
                    self._allocate_memory(full_frame, crop_l_bool, crop_r_bool)

                # Crop left and right regions from the full frame
                l = self._crop(full_frame, tracker_config.crop_left)
                r = self._crop(full_frame, tracker_config.crop_right)

                try:
                    # Write cropped frames to shared memory``
                    np.ndarray(tracker_config.memory_shape_l, dtype=l.dtype, buffer=self.shm_l.buf)[:] = l
                    np.ndarray(tracker_config.memory_shape_r, dtype=r.dtype, buffer=self.shm_r.buf)[:] = r
                    #print(f"[INFO] FrameProvider: Wrote frame {self.frame_id} to shared memory.")
                except Exception as e:
                    if module_list.health_monitor:
                        module_list.health_monitor.failure(
                            "FrameProvider",
                            f"Failed to write to shared memory: {e}"
                        )
                    print(f"[ERROR] FrameProvider: Failed to write to shared memory: {e}")
                    self.online = False
                    break

                try:
                    # Put frame ID in sync queues for both EyeLoop processes
                    self.sync_queue_l.put({"frame_id": self.frame_id, "type": "frame_id"})
                    self.sync_queue_r.put({"frame_id": self.frame_id, "type": "frame_id"})
                    #print(f"[INFO] FrameProvider: Put frame ID {self.frame_id} in sync queues.")
                except Exception as e:
                    if module_list.health_monitor:
                        module_list.health_monitor.failure(
                            "FrameProvider",
                            f"Failed to put frame ID in sync queue: {e}"
                        )
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
        while not (left_done and right_done) and self.online:
            now = time.time()
            if now - start_time > tracker_config.sync_timeout:
                print(f"[WARN] FrameProvider: Timeout - total sync wait exceeded "
                      f"{tracker_config.sync_timeout} sec for frame {self.frame_id}")
                break

            try:
                if not left_done:
                    msg_l = self.acknowledge_queue_l.get(
                        timeout=tracker_config.provider_queue_timeout
                        )
                    if msg_l.get("type") == "ack" and msg_l.get("frame_id") == self.frame_id:
                        left_done = True
                        #print("[INFO] FrameProvider:
                        # f"Left EyeLoop acknowledged frame {self.frame_id}.")
            except Empty:
                pass

            try:
                if not right_done:
                    msg_r = self.acknowledge_queue_r.get(
                        timeout=tracker_config.provider_queue_timeout
                        )
                    if msg_r.get("type") == "ack" and msg_r.get("frame_id") == self.frame_id:
                        right_done = True
                        #print("[INFO] FrameProvider:"
                        # f"Right EyeLoop acknowledged frame {self.frame_id}.")
            except Empty:
                pass

            time.sleep(0.001)  # Small sleep to avoid busy waiting

        if not left_done and self.online:
            print("[WARN] FrameProvider: Left EyeLoop did not acknowledge frame "
                  f"{self.frame_id} in time.")
        if not right_done and self.online:
            print("[WARN] FrameProvider: Right EyeLoop did not acknowledge frame "
                  f"{self.frame_id} in time.")


    def is_online(self):
        """Check if the FrameProvider is online."""
        return self.online

    @property
    def currentframe_id(self):
        """Get the current frame ID."""
        return self.frame_id


    def _allocate_memory(self, frame, crop_l_bool, crop_r_bool):

        #self.validate_crop()  # Validate crop dimensions
        frame_width, frame_height = frame.shape
        tracker_config.full_frame_resolution = frame.shape
        self.shape = frame.shape

        print(f"[INFO] FrameProvider: Current crop: "
              f"{tracker_config.crop_left}, right: {tracker_config.crop_right}")

        if crop_l_bool:
            if module_list.queue_handler:
                module_list.queue_handler.detach_eyeloop_memory("L")
            time.sleep(0.1)  # Small delay to ensure proper detachment

            self.crop_l = tracker_config.crop_left

            x_rel_start_l, x_rel_end_l = self.crop_l[0]
            y_rel_start_l, y_rel_end_l = self.crop_l[1]

            x_start_l = int(x_rel_start_l * frame_width)
            x_end_l = int(x_rel_end_l * frame_width)

            # Compute y coordinates based of the frame actual size
            y_start_l = int(y_rel_start_l * frame_height)
            y_end_l = int(y_rel_end_l * frame_height)

            tracker_config.memory_shape_l[0] = x_end_l-x_start_l
            tracker_config.memory_shape_l[1] = y_end_l-y_start_l

            self.memory_size_l = tracker_config.memory_shape_l[0] * tracker_config.memory_shape_l[1]


            self.clean_memory("L")  # Clean up left eye memory if it exists
            try:
                if module_list.tracker_center:
                    module_list.tracker_center.reset_preview_memory("L")
            except:
                pass

            try:
                self.shm_l = SharedMemory(
                    name=tracker_config.sharedmem_name_left,
                    create=True,
                    size=self.memory_size_l)
            except Exception as e:
                if module_list.health_monitor:
                    module_list.health_monitor.failure(
                        "FrameProvider",
                        f"Failed to allocate shared memory: {e}"
                    )
                self.online = False
                raise RuntimeError(f"[ERROR] FrameProvider: Failed to allocate shared memory: {e}")

            if module_list.queue_handler and module_list.health_monitor:
                module_list.queue_handler.update_eyeloop_memory("L")
                module_list.health_monitor.status("FrameProvider", "Reallocated shared memory for eye: L")

            print("[INFO] FrameProvider: Reallocated left SHM.")
            print(f"[INFO] FrameProvider: Left memoryShape: {tracker_config.memory_shape_l}")

        if crop_r_bool:
            if module_list.queue_handler:
                module_list.queue_handler.detach_eyeloop_memory("R")
            time.sleep(0.1)  # Small delay to ensure proper detachment

            self.crop_r = tracker_config.crop_right

            x_rel_start_r, x_rel_end_r = self.crop_r[0]
            y_rel_start_r, y_rel_end_r = self.crop_r[1]

            x_start_r = int(x_rel_start_r * frame_width)
            x_end_r = int(x_rel_end_r * frame_width)

            # Compute y coordinates based of the frame actual size
            y_start_r = int(y_rel_start_r * frame_height)
            y_end_r = int(y_rel_end_r * frame_height)

            tracker_config.memory_shape_r[0] = x_end_r-x_start_r
            tracker_config.memory_shape_r[1] = y_end_r-y_start_r

            self.memory_size_r = tracker_config.memory_shape_r[0] * tracker_config.memory_shape_r[1]

            self.clean_memory("R")  # Clean up left eye memory if it exists

            try:
                if module_list.tracker_center:
                    module_list.tracker_center.reset_preview_memory("R")
            except:
                pass

            try:
                self.shm_r = SharedMemory(
                    name=tracker_config.sharedmem_name_right,
                    create=True,
                    size=self.memory_size_r)
            except Exception as e:
                if module_list.health_monitor:
                    module_list.health_monitor.failure(
                        "FrameProvider",
                        f"Failed to allocate shared memory: {e}"
                    )
                self.online = False
                raise RuntimeError(f"[ERROR] FrameProvider: Failed to allocate shared memory: {e}")

            if module_list.queue_handler and module_list.health_monitor:
                module_list.queue_handler.update_eyeloop_memory("R")
                module_list.health_monitor.status(
                    "FrameProvider",
                    "Reallocated shared memory for eye: R"
                )
            print("[INFO] FrameProvider: Reallocated right SHM.")
            print(f"[INFO] FrameProvider: Right memoryShape: {tracker_config.memory_shape_r}")


    def validate_crop(self):
        """Validates crop dimensions and resets to default if invalid."""
        (x0_l, x1_l), (y0_l, y1_l) = tracker_config.crop_left
        (x0_r, x1_r), (y0_r, y1_r) = tracker_config.crop_right

        if x0_l < 0 or x1_l > 0.5 or y0_l < 0 or y1_l > 1 or x0_l > x1_l or y0_l > y1_l:
            if module_list.health_monitor:
                module_list.health_monitor.status(
                    "FrameProvider",
                    "Invalid crop dimensions for left eye: "
                    f"{tracker_config.crop_left}, resetting to default."
                    )
            print(f"[WARN] FrameProvider: Invalid crop dimensions for left eye: "
                  f"{tracker_config.crop_left}, resetting to default.")
            tracker_config.crop_left = ((0, 0.5), (0, 1))

        if x0_r < 0.5 or x1_r > 1 or y0_r < 0 or y1_r > 1 or x0_r > x1_r or y0_r > y1_r:
            if module_list.health_monitor:
                module_list.health_monitor.status(
                    "FrameProvider",
                    "Invalid crop dimensions for right eye: "
                    f"{tracker_config.crop_right}, resetting to default."
                )
            print("[WARN] FrameProvider: Invalid crop dimensions for right eye: "
                  f"{tracker_config.crop_right}, resetting to default.")
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
        """Cleans up shared memory resources."""
        if side == "both" or side == "L":
            try:
                self.shm_l = SharedMemory(name=tracker_config.sharedmem_name_left)
                self.shm_l.unlink()
                self.shm_l.close()
                print("[INFO] FrameProvider: Cleaning up left FrameProvider resources.")
                try:
                    self.shm_l = None
                except:
                    pass
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"[WARNING] Forced memory cleanup error: {e}")


        if side == "both" or side == "R":
            try:
                self.shm_r = SharedMemory(name=tracker_config.sharedmem_name_right)
                self.shm_r.unlink()
                self.shm_r.close()
                print("[INFO] FrameProvider: Cleaning up right FrameProvider resources.")
                try:
                    self.shm_r = None
                except:
                    pass
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"[WARNING] Forced memory cleanup error: {e}")

    def stop(self):
        """Stops the FrameProvider and cleans up resources."""
        self.online = False
        time.sleep(0.5)
        self.clean_memory()

        if self.use_test_video:
            self.cap.release()
