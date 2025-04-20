from multiprocessing import Process
from vr_core.eye_tracker.run_eyeloop_process import run_eyeloop_process
from vr_core.config import EyeTrackerConfig

class TrackerHandler:
    def __init__(self, command_queue_L, command_queue_R, response_queue_L, response_queue_R, sync_queue_L, sync_queue_R):

        self.proc_left = Process(target=run_eyeloop_process, args=("L", EyeTrackerConfig.sharedmem_name_left, command_queue_L, response_queue_L, sync_queue_L))
        self.proc_right = Process(target=run_eyeloop_process, args=("R", EyeTrackerConfig.sharedmem_name_right, command_queue_R, response_queue_R, sync_queue_R))

        self.proc_left.start()
        self.proc_right.start()

    def wait(self):
        self.proc_left.wait()
        self.proc_right.wait()

    def stop(self):
        self.proc_left.terminate()
        self.proc_right.terminate()



if __name__ == "__main__":
    from multiprocessing import Queue
    command_queue_L = Queue()
    command_queue_R = Queue()

    response_queue_L = Queue()
    response_queue_R = Queue()

    sync_queue_L = Queue()
    sync_queue_R = Queue()

    handler = TrackerHandler(command_queue_L, command_queue_R, response_queue_L, response_queue_R, sync_queue_L, sync_queue_R)
    input("[TEST] TrackerHandler running. Press Enter to terminate...\n")
    handler.stop()