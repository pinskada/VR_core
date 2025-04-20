import sys
from vr_core.eye_tracker.eyeloop_module.eyeloop.run_eyeloop import EyeLoop

def run_eyeloop_process(eye: str, shm_name: str, command_queue, response_queue, sync_queue):
    """
    Launches the EyeLoop process from within a multiprocessing.Process context.
    Sets up sys.argv so EyeLoop's main() can parse CLI-style arguments,
    and optionally injects a command queue.
    """
    sys.argv = [
        "eyeloop",
        "--sharedmem", shm_name,
        "--side", eye
    ]
    EyeLoop(sys.argv[1:], logger=None, command_queue=command_queue, response_queue=response_queue, sync_queue=sync_queue)