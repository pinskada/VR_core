from multiprocessing import Process
from vr_core.eye_tracker.run_eyeloop_process import run_eyeloop_process
from vr_core.config import EyeTrackerConfig
import time
import threading
import vr_core.module_list as module_list

class TrackerHandler:
    def __init__(self, command_queue_L, command_queue_R, response_queue_L, response_queue_R, sync_queue_L, sync_queue_R, test_mode=False):
        self.online = True  # Indicates if the tracker is online

        module_list.tracker_handler = self  # Register this instance in the module list
        self.command_dispatcher = module_list.command_dispatcher  # Command dispatcher for handling commands
        self.health_monitor = module_list.health_monitor  # Health monitor instance
        self.frame_provider = module_list.frame_provider  # Frame provider instance for video acquisition

        self.test_mode = test_mode

        try:
            self.proc_left = Process(target=run_eyeloop_process, args=("L", EyeTrackerConfig.sharedmem_name_left, command_queue_L, response_queue_L, sync_queue_L, test_mode))
            self.proc_right = Process(target=run_eyeloop_process, args=("R", EyeTrackerConfig.sharedmem_name_right, command_queue_R, response_queue_R, sync_queue_R, test_mode))
        except Exception as e:
            self.health_monitor.failure("TrackerHandler", f"Failed to initialize Eyeloop processes: {e}")
            print("[TrackerHandler] Failed to initialize processes.")
            self.online = False
            return

        self.left_alive = True
        self.right_alive = True

        self.proc_left.start()
        self.proc_right.start()

        self.health_thread = threading.Thread(target=self._eyeloop_monitor, daemon=True)
        self.health_thread.start()
    
    def _eyeloop_monitor(self):
        while True:
            if not self.proc_left.is_alive() and self.left_alive:
                self.health_monitor.failure("Left EyeLoop", "Process is not responding.")             
                print("[HealthMonitor] Left EyeLoop process is not responding.")
                self.left_alive = False
                
            if not self.proc_right.is_alive() and self.right_alive:
                self.health_monitor.failure("Right EyeLoop", "Process is not responding.")               
                print("[HealthMonitor] Right EyeLoop process is not responding.")
                self.right_alive = False

            time.sleep(EyeTrackerConfig.eyeloop_health_check_interval)

    def is_online(self):
        return self.online and self.left_alive and self.right_alive


    def wait(self):
        self.proc_left.wait()
        self.proc_right.wait()

    def stop(self):
        if self.frame_provider:
            self.frame_provider.cleanup()
      
        if self.proc_left.is_alive():
            self.proc_left.terminate()
            self.proc_left.join(timeout=1)
            print("[TrackerHandler] Left EyeLoop process terminated.")
        else:
            print("[TrackerHandler] Left EyeLoop process already stopped.")

        if self.proc_right.is_alive():
            self.proc_right.terminate()
            self.proc_right.join(timeout=1)
            print("[TrackerHandler] Right EyeLoop process terminated.")
        else:
            print("[TrackerHandler] Right EyeLoop process already stopped.")



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