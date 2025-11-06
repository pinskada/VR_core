"""Mock camera module for testing purposes."""

import numpy as np
from numpy.typing import NDArray

from vr_core.config_service.config import Config
from vr_core.base_service import BaseService
from vr_core.utilities.logger_setup import setup_logger
from vr_core.ports.interfaces import ICameraService


class MockCamera(BaseService, ICameraService):
    """A mock camera class for testing purposes."""
    def __init__(
        self,
        config: Config,
    ) -> None:
        super().__init__("MockCamera")

        self.logger = setup_logger("MockCamera")

        self.cfg = config

        self.logger.info("Service initialized.")

# ---------- BaseService lifecycle ----------


    def _on_start(self) -> None:
        """Start the mock camera service."""
        self._ready.set()
        self.logger.info("Service started.")


    def _run(self) -> None:
        """Mock camera main loop."""
        while not self._stop.is_set():
            self._stop.wait(0.5)


    def _on_stop(self) -> None:
        """Stop the mock camera service."""
        self.logger.info("Service stopped.")

# -------- Public API --------

    def capture_frame(self) -> NDArray[np.uint8]:
        """Mock interface to capture a frame from the camera."""
        height, width = self.cfg.tracker.full_frame_resolution

        return np.zeros((height, width), dtype=np.uint8)
