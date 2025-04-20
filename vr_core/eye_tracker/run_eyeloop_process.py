import sys
from eyeloop.run_eyeloop import main as eyeloop_main

def run_eyeloop_process(eye: str, shm_name: str, command_queue):
    """
    Launches the EyeLoop process from within a multiprocessing.Process context.
    Sets up sys.argv so EyeLoop's main() can parse CLI-style arguments,
    and optionally injects a command queue.
    """
    sys.argv = [
        "eyeloop",
        "--sharedmem", shm_name,
        "--eye", eye
    ]
    eyeloop_main(command_queue=command_queue)