from multiprocessing import Process
from vr_core.eye_tracker.run_eyeloop import run_eyeloop
from vr_core.config import tracker_config
import time
import threading
import vr_core.module_list as module_list

class TrackerLauncher:
    def __init__(self, test_mode=False):
        self.online = True  # Indicates if the tracker is online

        module_list.tracker_launcher = self  # Register this instance in the module list
        self.command_dispatcher = module_list.command_dispatcher  # Command dispatcher for handling commands
        self.health_monitor = module_list.health_monitor  # Health monitor instance
        self.frame_provider = module_list.frame_provider  # Frame provider instance for video acquisition
        self.queue_handler = module_list.queue_handler

        self.command_queue_L, self.command_queue_R = self.queue_handler.get_command_queues()
        self.response_queue_L, self.response_queue_R = self.queue_handler.get_response_queues()
        self.sync_queue_L, self.sync_queue_R, self.acknowledge_queue_L, self.acknowledge_queue_R = self.queue_handler.get_sync_queues()

        self.test_mode = test_mode

        try:
            self.proc_left = Process(target=run_eyeloop, args=("Left", tracker_config.importer_name, tracker_config.sharedmem_name_left, tracker_config.blink_calibration_L, self.command_queue_L, self.response_queue_L, self.sync_queue_L, self.acknowledge_queue_L, test_mode))
            self.proc_right = Process(target=run_eyeloop, args=("Right", tracker_config.importer_name, tracker_config.sharedmem_name_right, tracker_config.blink_calibration_R, self.command_queue_R, self.response_queue_R, self.sync_queue_R, self.acknowledge_queue_R, test_mode))
        except Exception as e:
            self.health_monitor.failure("TrackerLauncher", f"Failed to initialize Eyeloop processes: {e}")
            print("[ERROR] TrackerLauncher: Failed to initialize processes.")
            self.online = False
            return

        self.left_alive = True
        self.right_alive = True
        
        print("[INFO] TrackerLauncher: Initializing Eyeloop processes...")
        self.proc_left.start()
        self.proc_right.start()
        time.sleep(tracker_config.process_launch_time)  # Allow some time for the processes to stabilize

        self.health_thread = threading.Thread(target=self._eyeloop_monitor, daemon=True)
        self.health_thread.start()
    
    def _eyeloop_monitor(self):
        while True:
            if not self.proc_left.is_alive() and self.left_alive:
                self.health_monitor.failure("Left EyeLoop", "Process is not responding.")             
                print("[ERROR] TrackerLauncher: Left EyeLoop process is not responding.")
                self.left_alive = False
                
            if not self.proc_right.is_alive() and self.right_alive:
                self.health_monitor.failure("Right EyeLoop", "Process is not responding.")               
                print("[ERROR] TrackerLauncher: Right EyeLoop process is not responding.")
                self.right_alive = False

            time.sleep(tracker_config.eyeloop_health_check_interval)

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
            print("[INFO] TrackerLauncher: Left EyeLoop process terminated.")
        else:
            print("[INFO] TrackerLauncher: Left EyeLoop process already stopped.")

        if self.proc_right.is_alive():
            self.proc_right.terminate()
            self.proc_right.join(timeout=1)
            print("[INFO] TrackerLauncher: Right EyeLoop process terminated.")
        else:
            print("[INFO] TrackerLauncher: Right EyeLoop process already stopped.")
