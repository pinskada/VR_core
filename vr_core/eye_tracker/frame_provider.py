"""Frame Provider Module"""

import queue
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import Event as MpEvent
from typing import Any
from threading import Event
from enum import Enum
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
import cv2

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.signals import CommRouterSignals, EyeTrackerSignals, TrackerSignals
from vr_core.raspberry_perif.camera_manager import CameraManager


class Eye(Enum):
    """Enum for eye identification."""
    LEFT = 0
    RIGHT = 1


class FrameProvider(BaseService):
    """Handles video acquisition, cropping, and shared memory distribution

    This module captures frames from a camera or a test video, crops them for left and right eyes,
    and writes them to shared memory for consumption by EyeLoop tracker processes or CommRouter.
    Video acquisition is handled in _provide_frame() method.
    Before proceeding, acknowledgments are awaited from both EyeLoop processes or CommRouter
    to ensure synchronization. This is done in _wait_for_sync() method.

    General video acquisition can be enabled or disabled via the provide_frames_s event.
    Crop settings and shared memory configurations are dynamically adjustable via
    configuration changes, which are handled in _on_config_changed() method. During such changes,
    frame provision is temporarily paused to ensure consistency using events hold_frames()
    and is_holding_frames().
    """

    def __init__(
        self,
        i_camera_manager: CameraManager,
        comm_router_s: CommRouterSignals,
        eye_tracker_s: EyeTrackerSignals,
        tracker_s: TrackerSignals,
        tracker_cmd_l_q: queue.Queue,
        tracker_cmd_r_q: queue.Queue,
        config: Config,
    ) -> None:
        super().__init__(name="FrameProvider")

        self.i_camera_manager = i_camera_manager

        self.tcp_enabled_s: Event = comm_router_s.tcp_send_enabled
        self.frame_ready_s: Event = comm_router_s.frame_ready
        self.comm_shm_is_closed_s: Event = comm_router_s.comm_shm_is_closed

        self.provide_frames_s: Event = tracker_s.provide_frames
        self.tracker_running_l_s: Event = tracker_s.tracker_running_l
        self.tracker_running_r_s: Event = tracker_s.tracker_running_r
        self.shm_active: MpEvent = tracker_s.shm_active
        self.left_eye_ready_s: MpEvent = tracker_s.eye_ready_l
        self.right_eye_ready_s: MpEvent = tracker_s.eye_ready_r

        self.tracker_shm_is_closed_l_s: MpEvent = eye_tracker_s.tracker_shm_is_closed_l
        self.tracker_shm_is_closed_r_s: MpEvent = eye_tracker_s.tracker_shm_is_closed_r

        self.tracker_cmd_l_q = tracker_cmd_l_q
        self.tracker_cmd_r_q = tracker_cmd_r_q

        self.cfg = config
        self._unsubscribe = config.subscribe("tracker", self._on_config_changed)

        self.online = False
        self.shm_left: SharedMemory
        self.shm_right: SharedMemory

        self.hold_frames: bool = False
        self.is_holding_frames: Event = Event()

        self.crop_l: tuple[tuple[float, float], tuple[float, float]]
        self.crop_r: tuple[tuple[float, float], tuple[float, float]]
        self.full_frame_shape: tuple[int, int]

        self.video_capture: Any

        self.frame_id: int

        self.use_test_video = False
        self.test_mode = False  # Flag for test mode


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Starts the FrameProvider service by allocating resources."""

        # Choose between test video or live camera
        if self.use_test_video:
            path = Path(self.cfg.tracker.test_video_path)

            if not path.is_file():
                print("[ERROR] FrameProvider: Test video not found: "
                    f"{self.cfg.tracker.test_video_path}")
                return

            self.video_capture = cv2.VideoCapture(self.cfg.tracker.test_video_path)

            if not self.video_capture.isOpened():
                print(f"[ERROR] FrameProvider: Failed to open test video: {path}")
                return

            print("[INFO] FrameProvider: Using test video for frame capture.")

        self._validate_crop()
        self._copy_settings_to_local()

        # Capture a test frame to determine actual crop size
        if self.use_test_video:
            ret, test_frame = self.video_capture.read()

            if not ret:
                self.online = False
                print("[ERROR] FrameProvider: Failed to read from test video.")
                return

            test_frame = cv2.cvtColor(test_frame, cv2.COLOR_BGR2GRAY)
            test_frame_shape = test_frame.shape

            self._activate_shm(test_frame_shape)
        else:
            # Allocate shared memory for left and right eye frames
            self._activate_shm()

        self.frame_id = 0  # Incremented with each new frame

        self.online = True
        self._ready.set()


    def _run(self) -> None:
        """Main loop for capturing and distributing frames."""
        while not self._stop.is_set():
            # Wait until frame provision is enabled
            if not self.provide_frames_s.is_set():
                if self.shm_active.is_set():
                    self._deactivate_shm()
                self._stop.wait(0.1)
                continue

            if not self.shm_active.is_set():
                self._activate_shm()

            # If holding frames due to config change, wait
            if self.hold_frames:
                # Signal that frames are being held (only once)
                if not self.is_holding_frames.is_set():
                    self.is_holding_frames.set()
                self._stop.wait(0.1)
                continue

            # Start providing frames
            self._provide_frame()
            self._wait_for_sync()


    def _on_stop(self) -> None:
        """Stops the FrameProvider and cleans up resources."""
        self.online = False
        self._deactivate_shm()

        if self.use_test_video:
            self.video_capture.release()


    def is_online(self) -> bool:
        """Check if the FrameProvider is online."""
        return self.online and self._thread.is_alive() and self._ready.is_set()


# ---------- Internals ----------

    def _provide_frame(self) -> None:
        """Captures, crops, and writes frames to shared memory."""

        # Capture next frame from video or camera
        if self.use_test_video:
            ret, full_frame = self.video_capture.read()
            if full_frame is None:
                print("[INFO] FrameProvider: End of video reached.")
                return
            full_frame = cv2.cvtColor(full_frame, cv2.COLOR_BGR2GRAY)

            if not ret:
                print("[INFO] FrameProvider: End of test video or read error.")
                self.online = False
                return
        else:
            full_frame = self.i_camera_manager.capture_frame()

        # Crop left and right regions from the full frame
        left_frame = self._crop(full_frame, self.crop_l)
        right_frame = self._crop(full_frame, self.crop_r)

        try:
            # Write cropped frames to shared memory
            np.ndarray(
                self.cfg.tracker.memory_shape_l,
                dtype=np.dtype(self.cfg.tracker.memory_dtype),
                buffer=self.shm_left.buf
                )[:] = left_frame
            np.ndarray(
                self.cfg.tracker.memory_shape_r,
                dtype=np.dtype(self.cfg.tracker.memory_dtype),
                buffer=self.shm_right.buf
            )[:] = right_frame
        except (ValueError, TypeError, MemoryError, BufferError) as e:
            print(f"[ERROR] FrameProvider: Failed to write to shared memory: {e}")
            self.online = False
            return

        # Increment frame ID
        self.frame_id += 1

        # Signal to CommRouter that a new frame is ready
        self.frame_ready_s.set()

        # Put frame ID in sync queues for both EyeLoop processes
        if self.tracker_running_l_s.is_set():
            self.tracker_cmd_l_q.put({"frame_id": self.frame_id})
        if self.tracker_running_r_s.is_set():
            self.tracker_cmd_r_q.put({"frame_id": self.frame_id})


    def _wait_for_sync(self) -> None:
        """Waits for both EyeLoop processes to confirm frame processing."""

        # Skip sync wait during tests
        if self.test_mode:
            return

        # Block until both EyeLoop processes confirm processing of current frame
        if not self.left_eye_ready_s.wait(self.cfg.tracker.sync_timeout):
            print("[WARN] FrameProvider: Timeout waiting for left eye readiness.")
        if not self.right_eye_ready_s.wait(self.cfg.tracker.sync_timeout):
            print("[WARN] FrameProvider: Timeout waiting for right eye readiness.")

        self.left_eye_ready_s.clear()
        self.right_eye_ready_s.clear()

    # pylint: disable=unused-argument
    def _on_config_changed(self, path: str, old_val: Any, new_val: Any) -> None:
        """Handle configuration changes."""

        if (path == "tracker.crop_left"
            or path == "tracker.crop_right"
            or path == "tracker.full_frame_resolution"
        ):
            self.hold_frames = True
            self.is_holding_frames.wait(self.cfg.tracker.frame_hold_timeout)
            self._validate_crop()
            self._copy_settings_to_local()
            self._deactivate_shm()
            self._activate_shm()
            self.hold_frames = False
            self.is_holding_frames.clear()


    def _copy_settings_to_local(self) -> None:
        """Copies/binds relevant tracker settings to local variables."""

        self.crop_l = self.cfg.tracker.crop_left
        self.crop_r = self.cfg.tracker.crop_right
        self.full_frame_shape = self.cfg.tracker.full_frame_resolution


    def _activate_shm(
        self,
        test_shape: tuple[int, int] | None = None
    ) -> None:
        """Activates shared memory usage."""
        # Allocate new shared memory
        self._allocate_memory(Eye.LEFT, test_shape)
        self._allocate_memory(Eye.RIGHT, test_shape)

        # Notify EyeLoop trackers about new shared memory configuration
        self._cmd_tracker_shm_reconfig(Eye.LEFT)
        self._cmd_tracker_shm_reconfig(Eye.RIGHT)

        # Signal that shared memory is active
        self.shm_active.set()


    def _deactivate_shm(self) -> None:
        """Deactivates shared memory usage."""

        # Signal to consumers that shared memory is being deactivated
        self.shm_active.clear()

        # Wait for consumers to close their shared memory references
        self._close_consumer_shm()

        # Only after all processes have released the shared memory, proceed
        self._clear_memory(Eye.LEFT)
        self._clear_memory(Eye.RIGHT)


    def _allocate_memory(
        self,
        side_to_allocate: Eye,
        test_shape: tuple[int, int] | None = None
    ) -> None:
        """Allocates shared memory for eye frames based on current crop settings."""

        # Extract full frame dimensions
        if test_shape is not None:
            frame_height, frame_width = test_shape
        else:
            frame_height, frame_width = self.full_frame_shape

        # Determine memory name and crop based on eye side
        match side_to_allocate:
            case Eye.LEFT:
                memory_name = self.cfg.tracker.sharedmem_name_left
                crop = self.crop_l
            case Eye.RIGHT:
                memory_name = self.cfg.tracker.sharedmem_name_right
                crop = self.crop_r

        # Extract relative crop coordinates
        x_rel_start, x_rel_end = crop[0]
        y_rel_start, y_rel_end = crop[1]

        # Compute x coordinates based on the frame actual size
        x_start = int(x_rel_start * frame_width)
        x_end = int(x_rel_end * frame_width)

        # Compute y coordinates based on the frame actual size
        y_start = int(y_rel_start * frame_height)
        y_end = int(y_rel_end * frame_height)

        # Determine memory shape and size based on crop
        memory_shape_x = x_end - x_start
        memory_shape_y = y_end - y_start
        memory_size = (
            memory_shape_x *
            memory_shape_y *
            np.dtype(self.cfg.tracker.memory_dtype).itemsize
        )

        # Allocate shared memory
        try:
            shm = SharedMemory(
                name=memory_name,
                create=True,
                size=memory_size)

        except (FileNotFoundError, PermissionError, OSError, BufferError, ValueError) as e:
            self.online = False
            print("[ERROR] FrameProvider: Failed to allocate shared memory "
                  f"for {side_to_allocate} eyeframe: {e}")
            return

        # Store shared memory reference and update config
        match side_to_allocate:
            case Eye.LEFT:
                self.shm_left = shm
                # self.cfg.tracker.memory_shape_l = (memory_shape_x, memory_shape_y)
                self.cfg.tracker.memory_shape_l = (memory_shape_y, memory_shape_x)
            case Eye.RIGHT:
                self.shm_right = shm
                # self.cfg.tracker.memory_shape_r = (memory_shape_x, memory_shape_y)
                self.cfg.tracker.memory_shape_r = (memory_shape_y, memory_shape_x)

        print(f"[INFO] FrameProvider: Allocated shared memory for "
              f"{side_to_allocate} eye: {memory_name}")


    def _clear_memory(self, side_to_allocate: Eye) -> None:
        """Cleans up shared memory resources."""

        match side_to_allocate:
            case Eye.LEFT:
                shm = self.shm_left
            case Eye.RIGHT:
                shm = self.shm_right

        try:
            if shm is not None:
                shm.close()
                shm.unlink()
                print(f"[INFO] FrameProvider: Cleaned shared memory for {side_to_allocate} eye.")
            else:
                print("[WARN] FrameProvider: No shared memory to clean "
                    f"for {side_to_allocate} eye.")
        except (FileNotFoundError, PermissionError, OSError, BufferError) as e:
            print(f"[ERROR] FrameProvider: Failed to clean shared memory for "
                  f"{side_to_allocate} eye: {e}")


    def _close_consumer_shm(self) -> None:
        """Closes shared memory in consumer processes."""

        # Signal CommRouter to close shared memory if TCP is enabled
        if self.tcp_enabled_s.is_set():
            self.comm_shm_is_closed_s.wait(self.cfg.tracker.memory_unlink_timeout)
            self.comm_shm_is_closed_s.clear()

        # Signal left EyeLoop tracker to close shared memory
        if self.tracker_running_l_s.is_set():
            self.tracker_shm_is_closed_l_s.wait(self.cfg.tracker.memory_unlink_timeout)
            self.tracker_shm_is_closed_l_s.clear()

        # Signal right EyeLoop tracker to close shared memory
        if self.tracker_running_r_s.is_set():
            self.tracker_shm_is_closed_r_s.wait(self.cfg.tracker.memory_unlink_timeout)
            self.tracker_shm_is_closed_r_s.clear()


    def _cmd_tracker_shm_reconfig(self, side: Eye) -> None:
        """Sends command to EyeLoop tracker to reconfigure shared memory."""

        match side:
            case Eye.LEFT:
                if self.tracker_running_l_s.is_set():
                    self.tracker_cmd_l_q.put({
                        "type": "shm_reconfig",
                        "shape": self.cfg.tracker.memory_shape_l
                    })
                else:
                    print("[WARN] FrameProvider: Cannot send shm_reconfig to left EyeLoop "
                          "tracker, it is not running.")
            case Eye.RIGHT:
                if self.tracker_running_r_s.is_set():
                    self.tracker_cmd_r_q.put({
                        "type": "shm_reconfig",
                        "shape": self.cfg.tracker.memory_shape_r
                    })
                else:
                    print("[WARN] FrameProvider: Cannot send shm_reconfig to right EyeLoop "
                          "tracker, it is not running.")


    def _validate_crop(self) -> None:
        """Validates crop dimensions and resets to default if invalid."""

        (x0_l, x1_l), (y0_l, y1_l) = self.cfg.tracker.crop_left
        (x0_r, x1_r), (y0_r, y1_r) = self.cfg.tracker.crop_right

        if x0_l < 0 or x1_l > 0.5 or y0_l < 0 or y1_l > 1 or x0_l > x1_l or y0_l > y1_l:
            print(f"[WARN] FrameProvider: Invalid crop dimensions for left eye: "
                  f"{self.cfg.tracker.crop_left}, resetting to default.")
            self.cfg.set("tracker.crop_left", ((0, 0.5), (0, 1)))

        if x0_r < 0.5 or x1_r > 1 or y0_r < 0 or y1_r > 1 or x0_r > x1_r or y0_r > y1_r:
            print("[WARN] FrameProvider: Invalid crop dimensions for right eye: "
                  f"{self.cfg.tracker.crop_right}, resetting to default.")
            self.cfg.set("tracker.crop_right", ((0.5, 1), (0, 1)))


    def _crop(self, frame: NDArray[np.uint8], region: tuple) -> NDArray[np.uint8]:
        """Crops a region from the given frame based on relative coordinates."""

        (x_rel_start, x_rel_end), (y_rel_start, y_rel_end) = region

        # frame_width, frame_height = frame.shape[:2]
        frame_height, frame_width = frame.shape[:2]

        # Compute x coordinates based of the frame actual size
        x_start = int(x_rel_start * frame_width)
        x_end = int(x_rel_end * frame_width)

        # Compute y coordinates based of the frame actual size
        y_start = int(y_rel_start * frame_height)
        y_end = int(y_rel_end * frame_height)

        # Extract ROI using crop coordinates
        # return frame[x_start:x_end, y_start:y_end]
        return frame[y_start:y_end, x_start:x_end]
