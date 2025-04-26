import sys
import time

def run_eyeloop(eye: str, importer_name: str, shm_name: str, blink_cal: str, command_queue, response_queue, sync_queue, acknowledge_queue, test_mode):
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
        "--auto_search", False,

        #"--video", "test_video/test_video.mp4",
    ]
    
    if not test_mode:
        from vr_core.eye_tracker.eyeloop_module.eyeloop.run_eyeloop import EyeLoop
        try:
            print(f"[INFO] run_eyeloop_process: Starting tracker for eye: {eye}.\n")
            EyeLoop(sys.argv[1:], logger=None,
                    command_queue=command_queue,
                    response_queue=response_queue,
                    sync_queue=sync_queue,
                    acknowledge_queue=acknowledge_queue
                    )

        except Exception as e:
            print(f"[ERROR] run_eyeloop_process: EyeLoop process for eye {eye} crashed: {e}")
            import traceback; traceback.print_exc()
    else:
        print(f"[INFO] run_eyeloop_process: Test mode: EyeLoop process for eye {eye} would start here.")
        while True:
            # In test mode, we can simulate or mock the behavior of the EyeLoop process.
            # This is useful for unit tests where we don't want to start the actual process.
            time.sleep(1)
        # In test mode, we can simulate or mock the behavior of the EyeLoop process.
        # This is useful for unit tests where we don't want to start the actual process.
