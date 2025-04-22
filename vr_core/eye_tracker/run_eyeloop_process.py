import sys
import vr_core.health_monitor as health_monitor

def run_eyeloop_process(eye: str, shm_name: str, command_queue, response_queue, sync_queue, test_mode):
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

    if not test_mode:
        from vr_core.eye_tracker.eyeloop_module.eyeloop.run_eyeloop import EyeLoop
        try:
            EyeLoop(sys.argv[1:], logger=None,
                    command_queue=command_queue,
                    response_queue=response_queue,
                    sync_queue=sync_queue)
            print(f"[EyeLoopProcess] Starting tracker for {eye}, using shared memory: {shm_name}")

        except Exception as e:
            health_monitor.failure("EyeLoopProcess", f"EyeLoop process for eye {eye} did not start properly: {e}")
            print(f"[ERROR] EyeLoop process for eye {eye} crashed: {e}")
            import traceback; traceback.print_exc()
    else:
        health_monitor.status("EyeLoopProcess", f"Test mode: EyeLoop process for eye {eye} would start here.")
        print(f"[EyeLoopProcess] Test mode: EyeLoop process for eye {eye} would start here.")
        # In test mode, we can simulate or mock the behavior of the EyeLoop process.
        # This is useful for unit tests where we don't want to start the actual process.
        pass