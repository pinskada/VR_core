from multiprocessing import Queue
from frame_provider import FrameProvider
from tracker_handler import TrackerHandler
from multiprocessing import shared_memory
from vr_core.config import EyeTrackerConfig
from vr_core.config import CameraConfig

import threading
import time, numpy as np, cv2


class EyeTrackerCenter:
    def __init__(self, tcp_server):  # Initializes all tracking components and command queues
        self.tcp_server = tcp_server
        self.setup_mode = False
        self.ready_to_track = False
        self.sync_queue_L = Queue()
        self.sync_queue_R = Queue()
        self.frame_provider = None
        self.tracker_handler = None
        self.command_queue_L = Queue()
        self.command_queue_R = Queue()

    def handle_command(self, command: str):
        if command == "setup_tracker_1":
            self.setup_mode = True
            self.stop_preview()  # In case a previous preview was running
            self.frame_provider = FrameProvider(self.sync_queue_L, self.sync_queue_R)
            self.start_preview()
            print("[INFO] Setup phase 1: Preview started.")

        elif command == "setup_tracker_2":
            self.setup_mode = True
            self.stop_preview()
            self.tracker_handler = TrackerHandler(self.command_queue_L, self.command_queue_R)
            self.frame_provider = FrameProvider(self.sync_queue_L, self.sync_queue_R)
            self.frame_provider.run()
            print("[INFO] Setup phase 2: Tracker started after preview configuration.")

        elif command == "launch_tracker":
            self.setup_mode = False
            self.ready_to_track = True
            self.tracker_handler = TrackerHandler(self.command_queue_L, self.command_queue_R)
            self.frame_provider = FrameProvider(self.sync_queue_L, self.sync_queue_R)
            self.frame_provider.run()
            print("[INFO] Tracker launched directly from config.")

    def start_preview(self):  

        self.frame_provider = FrameProvider(self.sync_queue_L, self.sync_queue_R)
        self.setup_mode = True
        self.preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self.preview_thread.start()
        print("[INFO] Preview streaming started via preview loop.")
        # Start preview loop externally or in separate thread/process

    def _preview_loop(self):

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

            self.tcp_server.message_priorities.put_nowait(("eye_preview_L", jpg_L.tobytes(), "medium"))
            self.tcp_server.message_priorities.put_nowait(("eye_preview_R", jpg_R.tobytes(), "medium"))

            time.sleep(1 / EyeTrackerConfig.fps)

        print("[INFO] Preview streaming stopped.")


    def stop_preview(self):
        self.setup_mode = False
        if hasattr(self, 'preview_thread'):
            self.preview_thread.join()
        print("[INFO] Preview streaming stopped.")

        if self.frame_provider:
            self.frame_provider.cleanup()

    def start_tracker(self):
        self.tracker_handler = TrackerHandler(self.command_queue_L, self.command_queue_R)
        self.frame_provider.run()

    def stop_tracker(self):
        if self.tracker_handler:
            self.tracker_handler.stop()