
from multiprocessing import Process
from eye_tracker.run_eyeloop_process import run_eyeloop_process


class TrackerHandler:
    def __init__(self, command_queue_L, command_queue_R):
        self.proc_left = Process(target=run_eyeloop_process, args=("L", config.CameraConfig.sharedmem_name_left, command_queue_L))
        self.proc_right = Process(target=run_eyeloop_process, args=("R", config.CameraConfig.sharedmem_name_right, command_queue_R))

        self.proc_left.start()
        self.proc_right.start()

    def wait(self):
        self.proc_left.wait()
        self.proc_right.wait()

    def stop(self):
        self.proc_left.terminate()
        self.proc_right.terminate()