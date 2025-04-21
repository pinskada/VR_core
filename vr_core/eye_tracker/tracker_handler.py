from multiprocessing import Process
from vr_core.eye_tracker.run_eyeloop_process import run_eyeloop_process
from vr_core.config import EyeTrackerConfig
import time
import threading

class TrackerHandler:
    def __init__(self, tcp_server, frame_provider, command_queue_L, command_queue_R, response_queue_L, response_queue_R, sync_queue_L, sync_queue_R):

        self.tcp_server = tcp_server
        self.frame_provider = frame_provider  # Frame provider instance for video acquisition

        self.proc_left = Process(target=run_eyeloop_process, args=("L", EyeTrackerConfig.sharedmem_name_left, command_queue_L, response_queue_L, sync_queue_L))
        self.proc_right = Process(target=run_eyeloop_process, args=("R", EyeTrackerConfig.sharedmem_name_right, command_queue_R, response_queue_R, sync_queue_R))

        self.left_alive = True
        self.right_alive = True

        self.proc_left.start()
        self.proc_right.start()

        self.health_thread = threading.Thread(target=self._monitor_health, daemon=True)
        self.health_thread.start()
    
    def _monitor_health(self):
        while True:
            if not self.proc_left.is_alive() and self.left_alive:
                self.tcp_server.send({
                                        "type": "process_status",
                                        "eye": "L",
                                        "status": "dead"}, priority='low')
                
                print("[HealthMonitor] Left EyeLoop process is not responding.")
                self.left_alive = False
                
            if not self.proc_right.is_alive() and self.right_alive:
                self.tcp_server.send({
                                        "type": "process_status",
                                        "eye": "R",
                                        "status": "dead"}, priority='low')
                
                print("[HealthMonitor] Right EyeLoop process is not responding.")
                self.right_alive = False

            time.sleep(EyeTrackerConfig.health_check_interval)

        
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