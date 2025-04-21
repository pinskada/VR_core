# test_tracker_handler.py
from multiprocessing import Queue, set_start_method, Process
from vr_core.config import EyeTrackerConfig
from vr_core.eye_tracker.tracker_handler import TrackerHandler

# Only run once per Python session
try:
    set_start_method("spawn")
except RuntimeError:
    pass

class DummyTCPServer:
    def send(self, msg, priority="low"):
        print(f"[TCP-MOCK] Sent: {msg} with priority={priority}")

class DummyFrameProvider:
    def cleanup(self):
        print("[FrameProvider-MOCK] cleanup() called")

def test_tracker_handler_mocked():
    print("=== Starting test_tracker_handler_mocked ===")
    tcp_server = DummyTCPServer()

    command_queue_L = Queue()
    command_queue_R = Queue()
    response_queue_L = Queue()
    response_queue_R = Queue()
    sync_queue_L = Queue()
    sync_queue_R = Queue()

    frame_provider = DummyFrameProvider()

    handler = TrackerHandler(
        tcp_server,
        frame_provider,
        command_queue_L, command_queue_R,
        response_queue_L, response_queue_R,
        sync_queue_L, sync_queue_R, 
        test_mode=True, # Set test_mode to True to use the mocked EyeLoop process
    )

    print("[TEST] Waiting briefly...")
    import time
    time.sleep(2)

    print("[TEST] Stopping handler")
    handler.stop()
    print("=== test_tracker_handler_mocked PASSED ===")

if __name__ == "__main__":
    test_tracker_handler_mocked()
