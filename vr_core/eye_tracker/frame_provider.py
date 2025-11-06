"""Frame Provider Module"""

from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import Event as MpEvent
import multiprocessing as mp
from typing import Any, Optional
from threading import Event
from enum import Enum
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
import cv2

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.signals import CommRouterSignals, EyeTrackerSignals, TrackerSignals
from vr_core.ports.interfaces import ICameraService
from vr_core.utilities.logger_setup import setup_logger


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
        i_camera_manager: ICameraService,
        comm_router_s: CommRouterSignals,
        eye_tracker_s: EyeTrackerSignals,
        tracker_s: TrackerSignals,
        tracker_cmd_l_q: mp.Queue,
        tracker_cmd_r_q: mp.Queue,
        config: Config,
    ) -> None:
        super().__init__(name="FrameProvider")

        self.logger = setup_logger("FrameProvider")

        self.i_camera_manager = i_camera_manager

        self.tcp_enabled_s: Event = comm_router_s.tcp_send_enabled
        self.frame_ready_s: Event = comm_router_s.frame_ready
        self.comm_shm_is_closed_s: Event = comm_router_s.comm_shm_is_closed

        self.provide_frames_s: Event = tracker_s.provide_frames
        self.tracker_running_l_s: Event = tracker_s.tracker_running_l
        self.tracker_running_r_s: Event = tracker_s.tracker_running_r
        self.shm_active_s: MpEvent = tracker_s.shm_active
        self.left_eye_ready_s: MpEvent = tracker_s.eye_ready_l
        self.right_eye_ready_s: MpEvent = tracker_s.eye_ready_r

        self.tracker_shm_is_closed_l_s: MpEvent = eye_tracker_s.tracker_shm_is_closed_l
        self.tracker_shm_is_closed_r_s: MpEvent = eye_tracker_s.tracker_shm_is_closed_r

        self.tracker_cmd_l_q = tracker_cmd_l_q
        self.tracker_cmd_r_q = tracker_cmd_r_q

        self.cfg = config
        self._unsubscribe = config.subscribe("tracker", self._on_config_changed)

        self.online = False
        self.shm_left: Optional[SharedMemory] = None
        self.shm_right: Optional[SharedMemory] = None

        self.hold_frames: bool = False
        self.is_holding_frames: Event = Event()

        self.crop_l: tuple[tuple[float, float], tuple[float, float]]
        self.crop_r: tuple[tuple[float, float], tuple[float, float]]
        self.full_frame_shape: tuple[int, int]
        self.test_frame_shape: tuple[int, int]

        self.video_capture: Any

        self.frame_id: int

        self.use_test_video = False
        self.test_mode = False  # Flag for test mode

        self.logger.info("FrameProvider initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Starts the FrameProvider service by allocating resources."""

        # Choose between test video or live camera
        if self.use_test_video:
            path = Path(self.cfg.tracker.test_video_path)

            if not path.is_file():
                self.logger.error("Test video not found: %s",
                                  self.cfg.tracker.test_video_path)
                return

            self.video_capture = cv2.VideoCapture(self.cfg.tracker.test_video_path)

            if not self.video_capture.isOpened():
                self.logger.error("Failed to open test video: %s", path)
                return

            self.logger.info("Using test video for frame capture.")

        self._validate_crop()
        self._copy_settings_to_local()

        if self.use_test_video:
            # Capture a test frame to determine actual crop size
            ret, test_frame = self.video_capture.read()

            if not ret:
                self.online = False
                self.logger.error("Failed to read from test video.")
                return

            test_frame = cv2.cvtColor(test_frame, cv2.COLOR_BGR2GRAY)
            self.test_frame_shape = test_frame.shape

        self.frame_id = 0  # Incremented with each new frame

        self.online = True
        self._ready.set()

        self.logger.info("Service _ready is set.")


    def _run(self) -> None:
        """Main loop for capturing and distributing frames."""
        while not self._stop.is_set():

            # Wait until frame provision is enabled
            if not self.provide_frames_s.is_set():

                # If shared memory is active but frame provision is disabled, deactivate it
                if self.shm_active_s.is_set():
                    self._deactivate_shm()
                self._stop.wait(0.1)
                continue

            # If shared memory is not active, activate it
            if not self.shm_active_s.is_set():
                self._activate_shm()

            # If holding frames due to config change, wait
            if self.hold_frames:

                # Signal that frames are being held (only once)
                if not self.is_holding_frames.is_set():
                    self.is_holding_frames.set()
                    self.logger.info("Holding frames due to config change.")
                self._stop.wait(0.1)
                continue

            # Start providing frames
            self._provide_frame()
            self._wait_for_sync()


    def _on_stop(self) -> None:
        """Stops the FrameProvider and cleans up resources."""
        self.logger.info("Service stopping.")

        self.online = False
        self._deactivate_shm()

        if self.use_test_video:
            self.video_capture.release()
            self.logger.info("Test video released.")

        self._unsubscribe()


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
                self.logger.info("End of video reached.")
                return
            full_frame = cv2.cvtColor(full_frame, cv2.COLOR_BGR2GRAY)

            if not ret:
                self.logger.warning("End of test video or read error.")
                self.online = False
                return
        else:
            full_frame = self.i_camera_manager.capture_frame()

        # Crop left and right regions from the full frame
        left_frame = self._crop(full_frame, self.crop_l)
        right_frame = self._crop(full_frame, self.crop_r)

        if self.shm_left is None or self.shm_right is None:
            self.logger.error("Shared memory not allocated.")
            self.online = False
            return

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
            self.logger.error("Failed to write to shared memory: %s", e)
            self.online = False
            return

        # Increment frame ID
        self.frame_id += 1

        # Signal to CommRouter that a new frame is ready
        self.frame_ready_s.set()
        self.logger.info("frame_ready_s set for frame ID %d", self.frame_id)

        # Put frame ID in sync queues for both EyeLoop processes
        if self.tracker_running_l_s.is_set():
            self.tracker_cmd_l_q.put({"frame_id": self.frame_id})
        if self.tracker_running_r_s.is_set():
            self.tracker_cmd_r_q.put({"frame_id": self.frame_id})
        self.logger.info("tracker_cmd_l/r_q: frame ID %d sent.", self.frame_id)


    def _wait_for_sync(self) -> None:
        """Waits for both EyeLoop processes to confirm frame processing."""

        # Skip sync wait during tests
        if self.test_mode:
            return

        # Block until both EyeLoop processes confirm processing of current frame
        if not self.left_eye_ready_s.wait(self.cfg.tracker.sync_timeout):
            self.logger.warning("Timeout waiting for left eye readiness.")
        if not self.right_eye_ready_s.wait(self.cfg.tracker.sync_timeout):
            self.logger.warning("Timeout waiting for right eye readiness.")

        self.left_eye_ready_s.clear()
        self.right_eye_ready_s.clear()
        self.logger.info("left/right_eye_ready_s signals cleared.")

    # pylint: disable=unused-argument
    def _on_config_changed(self, path: str, old_val: Any, new_val: Any) -> None:
        """Handle configuration changes."""

        if (path == "tracker.crop_left"
            or path == "tracker.crop_right"
            or path == "tracker.full_frame_resolution"
        ):
            self.hold_frames = True
            self.logger.info("hold_frames flag set.")
            self.is_holding_frames.wait(self.cfg.tracker.frame_hold_timeout)
            self._validate_crop()
            self._copy_settings_to_local()
            self._deactivate_shm()
            self._activate_shm()
            self.hold_frames = False
            self.logger.info("hold_frames flag cleared.")
            self.is_holding_frames.clear()
            self.logger.info("Holding frames released after config change.")


    def _copy_settings_to_local(self) -> None:
        """Copies/binds relevant tracker settings to local variables."""

        self.crop_l = self.cfg.tracker.crop_left
        self.crop_r = self.cfg.tracker.crop_right
        self.full_frame_shape = self.cfg.tracker.full_frame_resolution
        self.logger.info("Local settings updated from config.")


    def _activate_shm(
        self,
    ) -> None:
        """Activates shared memory usage."""
        # Allocate new shared memory
        self._allocate_memory(Eye.LEFT)
        self._allocate_memory(Eye.RIGHT)

        # Signal that shared memory is active
        self.shm_active_s.set()
        self.logger.info("Shared memory activated.")

        # Notify EyeLoop trackers about new shared memory configuration
        self._cmd_tracker_shm_state()


    def _deactivate_shm(self) -> None:
        """Deactivates shared memory usage."""

        # Signal to consumers that shared memory is being deactivated
        self.shm_active_s.clear()
        self.logger.info("shm_active_s cleared.")

        # Wait for consumers to close their shared memory references
        self._close_consumer_shm()

        # Only after all processes have released the shared memory, proceed
        self._clear_memory(Eye.LEFT)
        self._clear_memory(Eye.RIGHT)


    def _allocate_memory(
        self,
        side_to_allocate: Eye,
    ) -> None:
        """Allocates shared memory for eye frames based on current crop settings."""

        # Extract full frame dimensions
        if self.use_test_video:
            # Use test frame dimensions
            frame_height, frame_width = self.test_frame_shape
        else:
            # Use configured full frame dimensions
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
            self.logger.error("Failed to allocate shared memory for %s eyeframe: %s",
                            side_to_allocate, e)
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

        self.logger.info("Allocated shared memory for %s eye: %s",
                        side_to_allocate, memory_name)


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
            else:
                self.logger.warning("No shared memory to clean "
                    "for %s eye.", side_to_allocate)
        except (FileNotFoundError, PermissionError, OSError, BufferError) as e:
            self.logger.error("Failed to clean shared memory for "
                "%s eye: %s", side_to_allocate, e)


    def _close_consumer_shm(self) -> None:
        """Closes shared memory in consumer processes.

        On Windows, shared memory segments are not released until all
        processes have closed their references. On the RPI memory will close automatically.
        This method signals the consumer processes to close their shared memory references.
        """

        # Signal CommRouter to close shared memory if TCP is enabled
        if self.tcp_enabled_s.is_set():
            if not self.comm_shm_is_closed_s.wait(self.cfg.tracker.memory_unlink_timeout):
                self.logger.error("Timeout waiting for CommRouter "
                      "to close shared memory.")

        # Signal left EyeLoop tracker to close shared memory
        if self.tracker_running_l_s.is_set():
            if not self.tracker_shm_is_closed_l_s.wait(self.cfg.tracker.memory_unlink_timeout):
                self.logger.error("Timeout waiting for left EyeLoop "
                      "tracker to close shared memory.")

        # Signal right EyeLoop tracker to close shared memory
        if self.tracker_running_r_s.is_set():
            if not self.tracker_shm_is_closed_r_s.wait(self.cfg.tracker.memory_unlink_timeout):
                self.logger.error("Timeout waiting for right EyeLoop "
                      "tracker to close shared memory.")


    def _cmd_tracker_shm_state(self) -> None:
        """Sends command to EyeLoop tracker to reconfigure shared memory."""

        if self.shm_active_s.is_set():
            if self.tracker_running_l_s.is_set():
                self.tracker_cmd_l_q.put({
                    "type": "shm_connect",
                    "frame_shape": self.cfg.tracker.memory_shape_l,
                    "frame_dtype": self.cfg.tracker.memory_dtype
                })

            if self.tracker_running_r_s.is_set():
                self.tracker_cmd_r_q.put({
                    "type": "shm_connect",
                    "frame_shape": self.cfg.tracker.memory_shape_r,
                    "frame_dtype": self.cfg.tracker.memory_dtype
                })
            self.logger.info("tracker_cmd_l/r_q: shm_connect sent"
                             "with frame_shape=%s, frame_dtype=%s.",
                             self.cfg.tracker.memory_shape_l,
                             self.cfg.tracker.memory_dtype)

        else:
            if self.tracker_running_l_s.is_set():
                self.tracker_cmd_l_q.put({
                    "type": "shm_detach",
                })

            if self.tracker_running_r_s.is_set():
                self.tracker_cmd_r_q.put({
                    "type": "shm_detach",
                })
            self.logger.info("tracker_cmd_l/r_q: shm_detach sent.")


    def _validate_crop(self) -> None:
        """Validates crop dimensions and resets to default if invalid."""

        (x0_l, x1_l), (y0_l, y1_l) = self.cfg.tracker.crop_left
        (x0_r, x1_r), (y0_r, y1_r) = self.cfg.tracker.crop_right

        if x0_l < 0 or x1_l > 0.5 or y0_l < 0 or y1_l > 1 or x0_l > x1_l or y0_l > y1_l:
            self.logger.warning("Invalid crop dimensions for left eye: "
                  "%s, resetting to default.", self.cfg.tracker.crop_left)
            self.cfg.set("tracker.crop_left", ((0, 0.5), (0, 1)))

        if x0_r < 0.5 or x1_r > 1 or y0_r < 0 or y1_r > 1 or x0_r > x1_r or y0_r > y1_r:
            self.logger.warning("Invalid crop dimensions for right eye: "
                  "%s, resetting to default.", self.cfg.tracker.crop_right)
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
