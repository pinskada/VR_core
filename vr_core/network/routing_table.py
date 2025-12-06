# ruff: noqa: ANN401, ERA001

"""Routing table and handlers for message handling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vr_core.network.comm_contracts import MessageType
from vr_core.utilities.logger_setup import setup_logger

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable
    from queue import Queue

    from vr_core.config_service.config import Config
    from vr_core.ports.interfaces import IGazeControl, IGazeService, ITrackerControl

logger = setup_logger("RoutingTable")

# --- Handlers ---

def handle_imu_cmd(
    msg: Any,
    imu_s: threading.Event,
) -> None:
    """Handle IMU command messages."""
    if msg == "SendOverTCP":
        imu_s.set()
    elif msg == "StopSending":
        imu_s.clear()
    else:
        logger.warning("Unknown IMU command: %s", msg)
    logger.info("Handling IMU command: %s", msg)


def handle_gaze_control(
    msg: Any,
    i_gaze_control: IGazeControl,
) -> None:
    """Handle gaze control messages."""
    logger.info("Handling gaze control: %s", msg)
    i_gaze_control.gaze_control(msg)


def handle_tracker_control(
    msg: Any,
    i_tracker_control: ITrackerControl,
) -> None:
    """Handle tracker control messages."""
    logger.info("Handling tracker control: %s", msg)
    i_tracker_control.tracker_control(msg)


def handle_esp_config(
    msg: Any,
    esp_cmd_q: Queue[Any],
) -> None:
    """Handle ESP configuration messages."""
    logger.info("Handling ESP config: %s", msg)
    esp_cmd_q.put(msg)


def handle_general_config(
    msg: Any,
    config: Config,
    config_ready_s: threading.Event,
) -> None:
    """Handle general configuration messages."""
    if not isinstance(msg, dict):
        logger.warning("Expected dict, got: %s", type(msg))
        return

    for path, value in msg.items():
        config.set(path, value)

        if not config_ready_s.is_set():
            logger.info("Set %s = %s", path, value)


# pylint: disable=unused-argument
def handle_config_ready(
    msg: Any,  # noqa: ARG001
    config_ready_s: threading.Event,
) -> None:
    """Handle configuration ready messages."""
    logger.info("Configuration is ready.")
    config_ready_s.set()


def handle_scene_marker(
    msg: Any,
    i_gaze_service: IGazeService,
) -> None:
    """Handle scene marker messages."""
    logger.info("Handling scene marker: %s", msg)
    i_gaze_service.set_timestamp(msg)


# --- Routing table factory ---
def build_routing_table(  # noqa: PLR0913
    imu_s: threading.Event,
    i_gaze_control: IGazeControl,
    i_gaze_service: IGazeService,
    i_tracker_control: ITrackerControl,
    esp_cmd_q: Queue[Any],
    config: Config,
    config_ready_s: threading.Event,
) -> dict[MessageType, Callable[[Any], None]]:
    """Routing table mapping message types to handler functions."""
    return {
        MessageType.imuSensor: lambda msg: handle_imu_cmd(msg, imu_s),
        MessageType.gazeCalcControl: lambda msg: handle_gaze_control(msg, i_gaze_control),
        MessageType.trackerControl: lambda msg: handle_tracker_control(msg, i_tracker_control),
        MessageType.espConfig: lambda msg: handle_esp_config(msg, esp_cmd_q),
        MessageType.tcpConfig: lambda msg: handle_general_config(msg, config, config_ready_s),
        MessageType.configReady: lambda msg: (handle_config_ready(msg, config_ready_s)),
        MessageType.sceneMarker: lambda msg: handle_scene_marker(msg, i_gaze_service),
    }
