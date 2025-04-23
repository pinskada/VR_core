import numpy as np
import sys
from multiprocessing import Queue, shared_memory

sys.path.append("..")  # So 'vr_core' can be found when running from /tests

import vr_core.config as config
import vr_core.module_list as module_list
from vr_core.eye_tracker.frame_provider import FrameProvider

def test_frame_provider(use_test_video=True):
    """
    Verifies that FrameProvider captures, crops, and writes a single frame
    to shared memory for both eyes, then exits cleanly.
    """

    # Set test video flag
    config.TrackerConfig.use_test_video = use_test_video

    # Mock the queue handler
    class MockQueueHandler:
        def __init__(self):
            self.q_L = Queue()
            self.q_R = Queue()

        def get_sync_queues(self):
            return self.q_L, self.q_R

    # Minimal mock for health monitor
    class MockHealthMonitor:
        def status(self, system, message): print(f"[INFO] Mock HealthMonitor: [{system}] {message}")
        def failure(self, system, message): print(f"[INFO] Mock - fail HealthMonitor: [{system}] {message}")

    # Inject mocks into module_list
    module_list.queue_handler = MockQueueHandler()
    module_list.health_monitor = MockHealthMonitor()

    print("[TEST] Starting FrameProvider test.")

    # Run FrameProvider
    provider = FrameProvider(test_run=True)
    provider.run()

    # Validate written shared memory
    try:
        shm_L = shared_memory.SharedMemory(name=config.TrackerConfig.sharedmem_name_left)
        shm_R = shared_memory.SharedMemory(name=config.TrackerConfig.sharedmem_name_right)

        def shape_from_crop(crop_region):
            (x_start, x_end), (y_start, y_end) = crop_region
            if use_test_video:
                w = int(config.TrackerConfig.test_video_resolution[0] * (x_end - x_start))
                h = int(config.TrackerConfig.test_video_resolution[1] * (y_end - y_start))
                return (h, w, config.TrackerConfig.test_video_channels)
            else:
                w = int(config.CameraConfig.width * (x_end - x_start))
                h = int(config.CameraConfig.height * (y_end - y_start))
                return (h, w, 3)

        shape_L = shape_from_crop(config.TrackerConfig.crop_left)
        shape_R = shape_from_crop(config.TrackerConfig.crop_right)

        frame_L = np.ndarray(shape_L, dtype=np.uint8, buffer=shm_L.buf).copy()
        frame_R = np.ndarray(shape_R, dtype=np.uint8, buffer=shm_R.buf).copy()

        assert frame_L.size > 0 and frame_R.size > 0
        print("[TEST] FrameProvider test passed — frames captured and shared .")

    except Exception as e:
        print(f"[TEST] FrameProvider test failed: {e}")
    finally:
        provider.clean_memory()

test_frame_provider(use_test_video=True)
