"""Camera manager for Raspberry Pi using Picamera2."""

import sys
from typing import TYPE_CHECKING, Any, Optional
from threading import Event

import numpy as np
from numpy.typing import NDArray

# --- Picamera2 imports with safe fallbacks for Windows/Pylance ---
try:
    from picamera2 import Picamera2 as Picamera2Runtime  # type: ignore  # pylint: disable=import-error
    # Some deployments expose these under different modules; guard defensively:
    try:
        # Prefer the named exceptions if available
        from picamera2.picamera2 import PiCameraError  # type: ignore  # pylint: disable=import-error
    except ImportError:  # noqa: BLE001 - import guard only
        class PiCameraError(Exception):  # type: ignore[no-redef]
            """Fallback when PiCamera2 is unavailable."""

    try:
        from picamera2.controls import ControlError  # type: ignore  # pylint: disable=import-error
    except ImportError:  # noqa: BLE001 - import guard only
        class ControlError(Exception):  # type: ignore[no-redef]
            """Fallback when PiCamera2 controls are unavailable."""
except (ImportError, ModuleNotFoundError, AttributeError):
    # Full fallback for non-RPi platforms so the module still imports & lints
    Picamera2Runtime = None  # type: ignore[assignment]  # pylint: disable=invalid-name
    class PiCameraError(Exception):  # type: ignore[no-redef]
        """Dummy PiCameraError when Picamera2 is unavailable."""

    class ControlError(Exception):  # type: ignore[no-redef]
        """Dummy ControlError when Picamera2 controls are unavailable."""


from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.interfaces import ICameraService
from vr_core.utilities.logger_setup import setup_logger


if TYPE_CHECKING:
    from picamera2 import Picamera2 as Picamera2Type  # type: ignore[import]
else:
    Picamera2Type = Any


class CameraManager(BaseService, ICameraService):
    """ Manages the Raspberry Pi camera using Picamera2."""
    def __init__(
        self,
        config: Config
    ) -> None:
        super().__init__("CameraManager")

        self.logger = setup_logger("CameraManager")

        self.cfg = config
        self._unsubscribe = config.subscribe(
            "camera",
            self._on_config_changed
        )
        self._unsubscribe = config.subscribe(
            "tracker.full_frame_resolution",
            self._on_config_changed
        )

        self.online = False
        self.frame_id = 0
        self._current_size: Optional[tuple[int, int]] = None
        self.width: int
        self.height: int

        self.reconfiguring_s = Event()

        self.picam2: Optional[Picamera2Type] = None

        self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Initialize camera resources."""

        if Picamera2Runtime is None:
            self.logger.warning("Picamera2 not available on this platform; running without camera.")
            self.online = False
            self._ready.set()
            return

        # Prevent initialization during interpreter shutdown
        if not hasattr(sys, 'is_finalizing') or not sys.is_finalizing():
            try: # type: ignore
                self.picam2 = Picamera2Runtime()  # Initialize camera object
            except (ImportError, RuntimeError, PiCameraError) as e:
                self.logger.error("Picamera2 not available: %s", e)
                self.online = False
                return
        else:
            self.logger.error("CameraManager: Picamera2 not available, sys is finalizing.")
            return

        if self._start_camera():
            self.online = True
        else:
            self.online = False
            return

        self.reconfiguring_s.set()

        self._ready.set()
        self.logger.info("_ready set.")


    def _run(self) -> None:
        """Main service loop."""
        while not self._stop.is_set():
            self._stop.wait(0.2)


    def _on_stop(self) -> None:
        """Cleanup camera resources."""
        self.logger.info("Stopping service.")
        self.online = False
        self._stop_camera()
        self._unsubscribe()

    def is_online(self):
        """ Check if the camera is online."""
        return self.online


# -------- Public API --------

    def capture_frame(self) -> NDArray[np.uint8]:
        """ Capture a single frame from the camera."""

        if self.picam2 is None:
            self.logger.error("capture_frame() called but Picamera2 is unavailable.")
            return np.zeros(
                (int(self.cfg.camera.height), int(self.cfg.camera.width)),
                dtype=np.uint8
            )

        self.frame_id += 1

        self.reconfiguring_s.wait(self.cfg.camera.reconfig_interval)

        last_exc: Optional[BaseException] = None

        for _ in range(self.cfg.camera.capture_retries):
            req = None
            try:
                # OR for async non-blocking
                req = self.picam2.capture_request(timeout=self.cfg.camera.capture_timeout_ms)
                if req is None:
                    raise TimeoutError("capture_request() returned None")

                arr = req.make_array("main")[0:self.height, 0:self.width]  # Y plane
                gray = np.ascontiguousarray(arr)

                last_exc = None
                break
            except (TimeoutError, OSError, RuntimeError, PiCameraError) as e:
                last_exc = e
                self.logger.warning("Transient capture error: %s", e)
            finally:
                try:
                    if req is not None:
                        req.release()
                except (RuntimeError, OSError, PiCameraError):
                    # Don't let a release issue crash the service
                    self.logger.debug("Request release failed (ignored).")

        if last_exc is not None or gray is None:
            self.logger.error("Capture failed after retries: %s", last_exc)
            self.online = False
            return np.zeros(
                (int(self.cfg.camera.height), int(self.cfg.camera.width)),
                dtype=np.uint8
            )

        return gray


# ---------- Internals ----------

    def _start_camera(self) -> bool:
        """ Start the camera with the configured settings."""
        if self.picam2 is None:
            return False

        try:
            self._apply_config()
            self.picam2.start()
            self.logger.info("Camera started.")
            return True
        except (OSError, RuntimeError, PiCameraError, ControlError) as e:
            self.logger.error("Failed to start camera: %s", e)
            return False


    def _stop_camera(self):
        """ Stop the camera."""
        if self.picam2 is None:
            return
        try:
            self.picam2.stop()
            self.logger.info("Camera stopped.")
        except (OSError, RuntimeError, PiCameraError) as e:
            self.logger.error("Failed to stop camera: %s", e)


    def _apply_config(self):
        """ Apply camera configuration settings."""

        self.logger.info("Applying camera configuration.")

        if self.picam2 is None:
            return

        self.reconfiguring_s.clear()

        buffer_count = max(3, self.cfg.camera.buffer_count)

        # Apply image resolution and buffer settings
        cfg = self.picam2.create_video_configuration(
            main={"size": (self.width, self.height), "format": "YUV420"},
            buffer_count=buffer_count,
        )

        try:
            self.picam2.configure(cfg)
            self._current_size = (self.width, self.height)
            self.logger.info("Configured video pipeline: %dx%d (buffers=%d).",
                self.width, self.height, buffer_count)
        except (OSError, RuntimeError, PiCameraError, ControlError) as e:
            self.logger.exception("Failed to configure camera: %s", e)
            return


        try:
            controls = {
                "AfMode": self.cfg.camera.af_mode,
                "LensPosition": int(self.cfg.camera.focus),
                "ExposureTime": int(self.cfg.camera.exposure_time),
                "AnalogueGain": self.cfg.camera.analogue_gain,
            }
            self.picam2.set_controls(controls)
            self.logger.debug("Controls applied: %s", controls)
        except (AttributeError, TypeError, ValueError, OSError, RuntimeError, PiCameraError) as e:
            self.logger.error("Failed to set controls: %s", e)

        self.reconfiguring_s.set()


    def _copy_config_to_local(self) -> None:
        """ Copy relevant config settings to local variables."""
        (self.width, self.height) = self.cfg.tracker.full_frame_resolution


    #  pylint: disable=unused-argument
    def _on_config_changed(self, path: str, old_val: Any, new_val: Any) -> None:
        """Handle configuration changes."""
        if self.picam2 is None:
            return

        self._copy_config_to_local()

        try:
            self.picam2.stop()
            self._stop.wait(0.1)
        except (RuntimeError, OSError, PiCameraError):
            self.logger.error("Stop during reconfigure ignored.")

        self._apply_config()

        try:
            self.picam2.start()
        except (OSError, RuntimeError, PiCameraError, ControlError) as e:
            self.logger.exception("Failed to restart camera after reconfigure: %s", e)
            self.online = False
            return
