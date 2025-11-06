"""Routing table and handlers for message handling."""

from typing import Callable, Dict, Any
from queue import Queue
import threading

from vr_core.network.comm_contracts import MessageType
from vr_core.config_service.config import Config
from vr_core.ports.interfaces import IGazeControl, ITrackerControl


# --- Handlers ---

def handle_imu_cmd(
    msg: Any,
    imu_s: threading.Event
) -> None:
    """Handle IMU command messages."""
    if msg == "SendOverTCP":
        imu_s.set()
    elif msg == "StopSending":
        imu_s.clear()
    else:
        print("Unknown IMU command:", msg)
    print("Handling IMU command:", msg)


def handle_gaze_control(
    msg: Any,
    i_gaze_control: IGazeControl
) -> None:
    """Handle gaze control messages."""
    i_gaze_control.gaze_control(msg)
    print("Handling gaze control:", msg)


def handle_tracker_control(
    msg: Any,
    i_tracker_control: ITrackerControl
) -> None:
    """Handle tracker control messages."""
    i_tracker_control.tracker_control(msg)
    print("Handling tracker control:", msg)


def handle_esp_config(
    msg: Any,
    esp_cmd_q: Queue
) -> None:
    """Handle ESP configuration messages."""
    esp_cmd_q.put(msg)
    print("Handling ESP config:", msg)


def handle_general_config(
    msg: Any,
    config: Config
) -> None:
    """Handle general configuration messages."""
    if not isinstance(msg, dict):
        print("[ConfigHandler] Expected dict, got:", type(msg))
        return

    for path, value in msg.items():
        config.set(path, value)
        print(f"[ConfigHandler] Set {path} = {value}")


def handle_config_ready(
    msg: Any,
    config_ready_s: threading.Event
) -> None:
    """Handle configuration ready messages."""
    print("Configuration is ready:", msg)
    config_ready_s.set()


# --- Routing table factory ---
def build_routing_table(
    imu_s: threading.Event,
    i_gaze_control: IGazeControl,
    i_tracker_control: ITrackerControl,
    esp_cmd_q: Queue,
    config: Config,
    config_ready_s: threading.Event
) -> Dict[MessageType, Callable[[Any], None]]:
    """Routing table mapping message types to handler functions."""
    return {
        MessageType.imuSensor: lambda msg: handle_imu_cmd(msg, imu_s),
        MessageType.gazeCalcControl: lambda msg: handle_gaze_control(msg, i_gaze_control),
        MessageType.trackerControl: lambda msg: handle_tracker_control(msg, i_tracker_control),
        MessageType.espConfig: lambda msg: handle_esp_config(msg, esp_cmd_q),
        MessageType.tcpConfig: lambda msg: handle_general_config(msg, config),
        MessageType.configReady: lambda msg: (handle_config_ready(msg, config_ready_s)),
    }
