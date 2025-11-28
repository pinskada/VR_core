# ruff: noqa: TRY400

"""Start EyeLoop process from within a multiprocessing.Process context."""

import multiprocessing as mp
import signal
import sys
import time
import traceback
from multiprocessing.synchronize import Event as MpEvent

from vr_core.eye_tracker.eyeloop_module.eyeloop.run_eyeloop import EyeLoop
from vr_core.utilities.logger_setup import setup_logger

logger = setup_logger("eyeloop_exe")

# pylint: disable=unused-argument
def run_eyeloop(  # noqa: PLR0913
    eye: str,
    importer_name: str,
    shm_name: str,
    eyeloop_model: str,
    tracker_cmd_q: mp.Queue,
    tracker_resp_q: mp.Queue,
    eye_ready_s: MpEvent,
    tracker_shm_is_closed_s: MpEvent,
    tracker_running_s: MpEvent,
    use_gui: bool = False,  # noqa: FBT001, FBT002
    processor_timing: str = "none",
    engine_timing: str = "none",
    test_mode: bool = False,  # noqa: FBT001, FBT002
    ) -> None:
    """Launch the EyeLoop process from within a multiprocessing.Process context.

    Sets up sys.argv so EyeLoop's main() can parse CLI-style arguments,
    and optionally injects a command queue.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    gui_flag = "1" if use_gui else "0"

    sys.argv = [
        "eyeloop",
        "--side", eye,
        "--importer", importer_name,
        "--sharedmem", shm_name,
        "--use_gui", gui_flag,
        "--model", eyeloop_model,
        "--proc_profiling", processor_timing,
        "--eng_profiling", engine_timing,
    ]

    if not test_mode:
        try:
            # logger.info("Starting tracker for eye: %s.", eye)
            EyeLoop(
                sys.argv[1:],
                tracker_cmd_q=tracker_cmd_q,
                tracker_response_q=tracker_resp_q,
                eye_ready_signal=eye_ready_s,
                tracker_shm_is_closed_s=tracker_shm_is_closed_s,
                tracker_running_s=tracker_running_s,
            )
        except Exception as e:  # pylint: disable=broad-except  # noqa: BLE001
            logger.error("EyeLoop process for eye %s crashed: %s", eye, e)
            traceback.print_exc()
    else:
        logger.info("run_eyeloop_process: Test mode: "
              "EyeLoop process for eye %s would start here.", eye)
        while True:
            # In test mode, we can simulate or mock the behavior of the EyeLoop process.
            # This is useful for unit tests where we don't want to start the actual process.
            time.sleep(1.0)
