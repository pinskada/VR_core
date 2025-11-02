"""Global interfaces definition."""

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
from numpy.typing import NDArray

from vr_core.network.comm_contracts import MessageType

class INetworkService(ABC):
    """Network service interface."""

    @abstractmethod
    def tcp_send(self, payload: Any, message_type: MessageType) -> None:
        """Send data over TCP."""


class IGazeService(ABC):
    """Gaze service interface."""

    @abstractmethod
    def gaze_control(self, msg) -> None:
        """Control the gaze module."""


class ITrackerService(ABC):
    """Tracker service interface."""

    @abstractmethod
    def tracker_control(self, msg) -> None:
        """Control the tracker module."""

    @abstractmethod
    def start_tracker(self, test_mode: bool = False) -> None:
        """Start the tracker."""

    @abstractmethod
    def stop_tracker(self) -> None:
        """Stop the tracker."""


class ICameraService(ABC):
    """Camera service interface."""

    @abstractmethod
    def capture_frame(self) -> NDArray[np.uint8]:
        """Capture a frame from the camera."""
