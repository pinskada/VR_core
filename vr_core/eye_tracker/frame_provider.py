import numpy as np
import time
import config
from multiprocessing import shared_memory, Queue

class FrameProvider:  # Handles video acquisition, cropping, and shared memory distribution
    def __init__(self, sync_queue_L: Queue, sync_queue_R: Queue):
        self.use_test_video = config.CameraConfig.use_test_video

        # Choose between test video or live camera
        if self.use_test_video:
            import cv2
            self.cv2 = cv2
            self.cap = cv2.VideoCapture(config.CameraConfig.test_video_path)
        else:
            from camera_config import CameraConfigManager
            self.cam_manager = CameraConfigManager()
            self.cam_manager.apply_config()

        # Capture a test frame to determine actual crop size
        if self.use_test_video:
            ret, test_frame = self.cap.read()
            if not ret:
                raise RuntimeError("Failed to read test frame from video.")
        else:
            test_frame = self.cam_manager.capture_frame()

        frame_height, frame_width = test_frame.shape[:2]
        channels = test_frame.shape[2] if len(test_frame.shape) == 3 else 1
        x_rel_start, x_rel_end = config.CameraConfig.crop_left[0]
        y_rel_start, y_rel_end = config.CameraConfig.crop_left[1]
        w = int((x_rel_end - x_rel_start) * frame_width)
        h = int((y_rel_end - y_rel_start) * frame_height)

        self.shm_L = shared_memory.SharedMemory(name=config.CameraConfig.sharedmem_name_left, create=True, size=h * w * channels)
        self.shm_R = shared_memory.SharedMemory(name=config.CameraConfig.sharedmem_name_right, create=True, size=h * w * channels)

        self.frame_id = 0  # Incremented with each new frame
        self.sync_queue_L = sync_queue_L  # Queue to track left EyeLoop completion
        self.sync_queue_R = sync_queue_R  # Queue to track right EyeLoop completion

    def run(self):
        try:
          while True:
              # Capture next frame from video or camera
              if self.use_test_video:
                  ret, full_frame = self.cap.read()
                  if not ret:
                      print("End of test video or read error.")
                      break
              else:
                  full_frame = self.cam_manager.capture_frame()
  
              ts = time.time()
  
              # Crop left and right regions from the full frame
              l = self._crop(full_frame, config.CameraConfig.crop_left)
              r = self._crop(full_frame, config.CameraConfig.crop_right)
  
              # Write cropped frames to shared memory
              np.ndarray(l.shape, dtype=l.dtype, buffer=self.shm_L.buf)[:] = l
              np.ndarray(r.shape, dtype=r.dtype, buffer=self.shm_R.buf)[:] = r
  
              # Block until both EyeLoop processes confirm processing of current frame
              left_done = right_done = False
              while not (left_done and right_done):
                  try:
                      msg_L = self.sync_queue_L.get(timeout=config.CameraConfig.sync_timeout)
                      if msg_L.get("frame_id") == self.frame_id:
                          left_done = True
                  except Exception:
                      print(f"[WARN] Timeout waiting for left EyeLoop on frame {self.frame_id}")
                      break
  
                  try:
                      msg_R = self.sync_queue_R.get(timeout=config.CameraConfig.sync_timeout)
                      if msg_R.get("frame_id") == self.frame_id:
                          right_done = True
                  except Exception:
                      print(f"[WARN] Timeout waiting for right EyeLoop on frame {self.frame_id}")
                      break
  
              self.frame_id += 1
              time.sleep(1 / config.CameraConfig.fps)  # Maintain target FPS
        finally:
            self.cleanup()

    def cleanup(self):
        print("[INFO] Cleaning up FrameProvider resources.")
        try:
            self.shm_L.close()
            self.shm_L.unlink()
        except FileNotFoundError:
            pass
        try:
            self.shm_R.close()
            self.shm_R.unlink()
        except FileNotFoundError:
            pass

        if self.use_test_video:
            self.cap.release()

    def _crop(self, frame, region):
        (x_rel_start, x_rel_end), (y_rel_start, y_rel_end) = region
        frame_height, frame_width = frame.shape[:2]

        # Compute x coordinates based of the frame actual size
        x_start = int(x_rel_start * frame_width)
        x_end = int(x_rel_end * frame_width)

        # Compute y coordinates based of the frame actual size
        y_start = int(y_rel_start * frame_height)
        y_end = int(y_rel_end * frame_height)

        # Extract ROI using crop coordinates
        return frame[y_start:y_end, x_start:x_end]