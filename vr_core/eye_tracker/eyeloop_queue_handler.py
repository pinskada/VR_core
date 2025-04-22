from multiprocessing import Queue
import threading
import time
import vr_core.module_list as module_list 
from vr_core.config import EyeTrackerConfig

class EyeLoopQueueHandler:
    """
    Contains the command and response queues for the EyeLoop processes.
    This class is used to manage the communication between the EyeLoop processes and the main process.
    """
    
    def __init__(self):
        self.online = True

        module_list.eyeloop_queue_handler = self  # Register the queue handler in the module list
        self.eye_tracker_centre = module_list.eye_tracker_centre  # Reference to the EyeTrackerCentre instance
        self.tcp_server = module_list.tcp_server  # Reference to the TCP server
        self.health_monitor = module_list.health_monitor  # Reference to the health check module

        try:
            # Initialize queues for both left and right EyeLoop processes
            self.command_queue_L = Queue()
            self.command_queue_R = Queue()
            self.response_queue_L = Queue()
            self.response_queue_R = Queue()
            self.sync_queue_L = Queue()
            self.sync_queue_R = Queue()
        except Exception as e:
            self.health_monitor.failure("EyeloopQueueHandler", f"Error initializing queues: {e}")
            print(f"[EyeloopQueueHandler] Error initializing queues: {e}")
            self.online = False
            raise

        try:
            self.response_thread = threading.Thread(target=self._response_loop, daemon=True)
            self.response_thread.start()
        except Exception as e:
            self.health_monitor.failure("EyeloopQueueHandler", f"Error starting _response_loop thread: {e}")
            print(f"[EyeloopQueueHandler] Error starting _response_loop thread: {e}")
            self.online = False
            raise

    def is_online(self):
        return self.online 

    def get_command_queues(self) -> tuple[Queue, Queue]:
        return self.command_queue_L, self.command_queue_R
    
    def get_response_queues(self) -> tuple[Queue, Queue]:
        return self.response_queue_L, self.response_queue_R
    
    def get_sync_queues(self) -> tuple[Queue, Queue]:
        return self.sync_queue_L, self.sync_queue_R
    
    def send_command(self, command: str, eye: str):
        """
        Sends a command to the specified EyeLoop process.
        """

        try:
            print(f"[QueueHandler] Sending command to {eye}: {command}")
            if eye == "L":
                self.command_queue_L.put(command)
            elif eye == "R":
                self.command_queue_R.put(command)
            else:
                raise ValueError("Invalid eye specified. Use 'L' or 'R'.")
        except Exception as e:
            self.health_monitor.failure("EyeloopQueueHandler", f"Error sending command to {eye}: {e}")
            print(f"[EyeloopQueueHandler] Error sending command to {eye}: {e}")
            self.online = False


    def _response_loop(self):
        while self.online:
            try:
                if not self.response_queue_L.empty():
                    msg_L = self.response_queue_L.get(timeout=EyeTrackerConfig.queue_timeout)

                    self.dispatch_message(msg_L, "Left")


                if not self.response_queue_R.empty():
                    msg_R = self.response_queue_R.get(timeout=EyeTrackerConfig.queue_timeout)
                    
                    self.dispatch_message(msg_R, "Right")


            except Exception as e:
                # Silently skip if queues are empty or error occurs
                time.sleep(EyeTrackerConfig.queue_timeout)


    def dispatch_message(self, message, eye: str):
        """
        Dispatches a message to the appropriate queue based on its content.
        """

        if isinstance(message, dict) and message.get("category") == "Data":
            if self.eye_tracker_centre.setup_mode:
                
                payload = message.get("payload")
                if payload is not None:
                    self.tcp_server.send(
                    {
                        "type": "EyeloopData", 
                        "eye": eye, 
                        "payload": payload
                    }, data_type='JSON', priority="medium")
                else:
                    self.health_monitor.failure("EyeloopQueueHandler", f"Missing 'payload' in message from response loop.from eye: {eye}")
                    print("[EyeloopQueueHandler] Warning: Missing 'payload' in message.")
            else:
                ### Send data to the main process for processing
                pass
        elif isinstance(message, bytes):
            self.tcp_server.send(message, data_type="PNG", priority="medium")
        else:
            self.health_monitor.failure("EyeloopQueueHandler", f"Unexpected message format: {type(message)}, content: {str(message)[:100]}")
            print(f"[EyeloopQueueHandler] Unexpected message format: {type(message)}, content: {str(message)[:100]}")





