"""Start EyeLoop process from within a multiprocessing.Process context."""

import sys
import time
import multiprocessing as mp
from multiprocessing.synchronize import Event as MpEvent
import traceback

from vr_core.eye_tracker.eyeloop_module.eyeloop.run_eyeloop import EyeLoop

def run_eyeloop(
    eye: str,
    importer_name: str,
    shm_name: str,
    blink_cal: str,
    tracker_cmd_q: mp.Queue,
    tracker_resp_q: mp.Queue,
    eye_ready_s: MpEvent,
    tracker_shm_is_closed_s: MpEvent,
    test_mode: bool = False,
    ) -> None:
    """
    Launches the EyeLoop process from within a multiprocessing.Process context.
    Sets up sys.argv so EyeLoop's main() can parse CLI-style arguments,
    and optionally injects a command queue.
    """

    sys.argv = [
        "eyeloop",
        "--side", eye,
        "--importer", importer_name,
        "--sharedmem", shm_name,
        "--auto_search", "false",

        #"--video", "test_video/test_video.mp4",
    ]

    if not test_mode:
        try:
            print(f"[INFO] run_eyeloop_process: Starting tracker for eye: {eye}.\n")
            EyeLoop(
                sys.argv[1:],
                command_queue=tracker_cmd_q,
                response_queue=tracker_resp_q,
                eye_ready_signal=eye_ready_s,
                tracker_shm_is_closed_signal=tracker_shm_is_closed_s,
                logger=None,
            )
        except Exception as e:
            print(f"[ERROR] run_eyeloop_process: EyeLoop process for eye {eye} crashed: {e}")
            traceback.print_exc()
    else:
        print("[INFO] run_eyeloop_process: Test mode: "
              f"EyeLoop process for eye {eye} would start here.")
        while True:
            # In test mode, we can simulate or mock the behavior of the EyeLoop process.
            # This is useful for unit tests where we don't want to start the actual process.
            time.sleep(1.0)
