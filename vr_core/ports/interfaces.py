"""Global interfaces definition."""

from abc import ABC, abstractmethod
import numpy as np

from vr_core.network.comm_contracts import MessageType

class INetworkService(ABC):
    """Network service interface."""

    @abstractmethod
    def tcp_send(self, payload, message_type: MessageType) -> None:
        """Send data over TCP."""


class IGazeService(ABC):
    """Gaze service interface."""

    @abstractmethod
    def gaze_control(self) -> None:
        """Control the gaze module."""


class ITrackerService(ABC):
    """Tracker service interface."""

    @abstractmethod
    def tracker_control(self) -> None:
        """Control the tracker module."""


class ICameraService(ABC):
    """Camera service interface."""

    @abstractmethod
    def capture_frame(self) -> np.ndarray:
        """Capture a frame from the camera."""
