"""Mock module to load and send calibration JSON data."""

from queue import PriorityQueue
from typing import Any
import json
import itertools
from dataclasses import asdict

from vr_core.network.comm_contracts import MessageType

def load_calib_json(
    comm_router_q: PriorityQueue[Any],
    pq_counter: itertools.count,
) -> None:
    """Load and send calibration JSON data to the communication router.

    Args:
        comm_router_q (PriorityQueue[Any]): Communication router queue.
    """
    # Path to your original csv file
    folder = "/home/VRberry/Public/VR_core/calib_log/"
    file_name = "results_"
    file_id = "1507"

    json_path = f"{folder}{file_name}{file_id}.json"

    # Load JSON data
    with open(json_path, "r") as f:
        data = json.load(f)

    calibrated_data_dict = data["calibrated_data"]
    print(calibrated_data_dict)

    comm_router_q.put((8, next(pq_counter), MessageType.calibData, calibrated_data_dict))
