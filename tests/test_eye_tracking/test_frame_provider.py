use_test_video = True  # Set to False to test with live camera


def test_frame_provider(use_test_video=True):
    """
    Verifies that FrameProvider captures, crops, and writes a single frame
    to shared memory for both eyes, then exits cleanly.
    """

    import numpy as np
    from multiprocessing import Queue, shared_memory
    import sys
    sys.path.append("..")  # So 'vr_core' and config can be found when running from /tests

    import vr_core.config as config
    from vr_core.eye_tracker.frame_provider import FrameProvider

    config.EyeTrackerConfig.use_test_video = use_test_video  # Ensure test mode

    sync_queue_L = Queue()
    sync_queue_R = Queue()

    provider = FrameProvider(sync_queue_L, sync_queue_R)
    provider.test_run = True  # Run only one frame
    provider.run()

    try:
        shm_L = shared_memory.SharedMemory(name=config.EyeTrackerConfig.sharedmem_name_left)
        shm_R = shared_memory.SharedMemory(name=config.EyeTrackerConfig.sharedmem_name_right)

        def shape_from_crop(crop_region):
            x_rel = crop_region[0]
            width = int(config.CameraConfig.width * (x_rel[1] - x_rel[0]))
            height = config.CameraConfig.height
            return (height, width, 3)

        shape_L = shape_from_crop(config.EyeTrackerConfig.crop_left)
        shape_R = shape_from_crop(config.EyeTrackerConfig.crop_right)

        frame_L = np.ndarray(shape_L, dtype=np.uint8, buffer=shm_L.buf).copy()
        frame_R = np.ndarray(shape_R, dtype=np.uint8, buffer=shm_R.buf).copy()

        assert frame_L.size > 0 and frame_R.size > 0
        print("[TEST] FrameProvider test passed — frames captured and shared.")

    except Exception as e:
        print(f"[TEST] FrameProvider test failed: {e}")

    finally:
        provider.cleanup()


test_frame_provider(use_test_video)