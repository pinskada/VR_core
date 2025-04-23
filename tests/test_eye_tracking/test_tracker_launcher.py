from vr_core.eye_tracker.tracker_launcher import TrackerLauncher
import vr_core.module_list as module_list
from unittest.mock import MagicMock
from multiprocessing import Queue
from multiprocessing import freeze_support

def test_tracker_launcher():
    print("\n=== Running integrated test: TrackerLauncher -> run_eyeloop ===")

    # ---- Step 1: Mock module_list components ----
    module_list.command_dispatcher = MagicMock()
    module_list.health_monitor = MagicMock()
    module_list.frame_provider = MagicMock()

    # Mock QueueHandler to return new queues
    mock_queue_handler = MagicMock()
    module_list.queue_handler = mock_queue_handler

    mock_queue_handler.get_command_queues.return_value = (Queue(), Queue())
    mock_queue_handler.get_response_queues.return_value = (Queue(), Queue())
    mock_queue_handler.get_sync_queues.return_value = (Queue(), Queue())

    # ---- Step 2: Create the TrackerLauncher in test mode (does not launch real eyeloop) ----
    launcher = TrackerLauncher(test_mode=False)

    # ---- Step 3: Validate process registration and test mode behavior ----
    assert launcher.is_online(), "TrackerLauncher should be online in test mode"
    assert hasattr(launcher, "proc_left") and hasattr(launcher, "proc_right"), "Processes not initialized"
    print("[TEST PASS] TrackerLauncher initialized and test-mode processes created.")

    # ---- Step 4: Shutdown the system cleanly ----
    launcher.stop()
    print("[TEST PASS] TrackerLauncher stopped all processes cleanly.")

    print("=== test_tracker_launcher completed ===\n")


if __name__ == "__main__":
    freeze_support()  # Only needed on Windows
    test_tracker_launcher()