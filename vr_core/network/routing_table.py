"""Routing table and handlers for message handling."""

from typing import Callable, Dict, Any
from queue import Queue

from vr_core.network.comm_contracts import MessageType
from vr_core.raspberry_perif.imu import Imu
from vr_core.gaze.gaze_control import GazeControl
from vr_core.eye_tracker.tracker_control import TrackerControl
from vr_core.config_service.config import Config


# --- Handlers ---

def handle_imu_cmd(
    msg: Any,
    imu: Imu
) -> None:
    """Handle IMU command messages."""
    imu.imu_cmd(msg)
    print("Handling IMU command:", msg)


def handle_gaze_control(
    msg: Any,
    gaze_control: GazeControl
) -> None:
    """Handle gaze control messages."""
    gaze_control.gaze_control(msg)
    print("Handling gaze control:", msg)


def handle_tracker_control(
    msg: Any,
    tracker_control: TrackerControl
) -> None:
    """Handle tracker control messages."""
    tracker_control.tracker_control(msg)
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


# --- Routing table factory ---
def build_routing_table(
    imu: Imu,
    gaze_control: GazeControl,
    tracker_control: TrackerControl,
    esp_cmd_q: Queue,
    config: Config,
) -> Dict[MessageType, Callable[[Any], None]]:
    return {
        MessageType.imuSensor: lambda msg: handle_imu_cmd(msg, imu),
        MessageType.gazeCalcControl: lambda msg: handle_gaze_control(msg, gaze_control),
        MessageType.trackerControl: lambda msg: handle_tracker_control(msg, tracker_control),
        MessageType.espConfig: lambda msg: handle_esp_config(msg, esp_cmd_q),
        MessageType.tcpConfig: lambda msg: handle_general_config(msg, config),
    }
