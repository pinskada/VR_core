from multiprocessing import Queue
import threading
import time
import vr_core.module_list as module_list 
from vr_core.config import tracker_config

class QueueHandler:
    """
    Contains the command and response queues for the EyeLoop processes.
    This class is used to manage the communication between the EyeLoop processes and the main process.
    """
    
    def __init__(self):
        self.online = True

        module_list.queue_handler = self  # Register the queue handler in the module list
        self.tracker_center = module_list.tracker_center  # Reference to the EyeTrackerCentre instance
        self.tcp_server = module_list.tcp_server  # Reference to the TCP server
        self.health_monitor = module_list.health_monitor  # Reference to the health check module

        self.frame_id_left = None
        self.frame_id_right = None

        try:
            # Initialize queues for both left and right EyeLoop processes
            self.command_queue_L = Queue()
            self.command_queue_R = Queue()
            self.response_queue_L = Queue()
            self.response_queue_R = Queue()
            self.sync_queue_L = Queue()
            self.sync_queue_R = Queue()
            self.acknowledge_queue_L = Queue()
            self.acknowledge_queue_R = Queue()
        except Exception as e:
            self.health_monitor.failure("QueueHandler", f"Error initializing queues: {e}")
            print(f"[ERROR] QueueHandler: Error initializing queues: {e}")
            self.online = False
            raise

        try:
            self.response_thread = threading.Thread(target=self._response_loop, daemon=True)
            self.response_thread.start()
        except Exception as e:
            self.health_monitor.failure("QueueHandler", f"Error starting _response_loop thread: {e}")
            print(f"[ERROR] QueueHandler: Error starting _response_loop thread: {e}")
            self.online = False
            raise

    def is_online(self):
        return self.online 

    def get_command_queues(self):
        return self.command_queue_L, self.command_queue_R
    
    def get_response_queues(self):
        return self.response_queue_L, self.response_queue_R
    
    def get_sync_queues(self):
        return self.sync_queue_L, self.sync_queue_R, self.acknowledge_queue_L, self.acknowledge_queue_R
    
    def send_command(self, command: dict, eye: str):
        """
        Sends a command to the specified EyeLoop process.
        """

        try:
            print(f"[INFO] QueueHandler: Sending command to {eye}: {command}")
            if eye == "L":
                self.command_queue_L.put(command)
            elif eye == "R":
                self.command_queue_R.put(command)
            else:
                raise ValueError("[ERROR] QueueHandler: Invalid eye specified. Use 'L' or 'R'.")
        except Exception as e:
            self.health_monitor.failure("QueueHandler", f"Error sending command to {eye}: {e}")
            print(f"[ERROR] QueueHandler: Error sending command to {eye}: {e}")
            self.online = False


    def _response_loop(self):
        while self.online:
            try:
                msg_L = self.response_queue_L.get(timeout=tracker_config.queue_timeout)
                self.dispatch_message(msg_L, "Left")

                msg_R = self.response_queue_R.get(timeout=tracker_config.queue_timeout)
                self.dispatch_message(msg_R, "Right")

            except Exception:
                # Silently skip if queues are empty or error occurs
                time.sleep(tracker_config.queue_timeout)


    def dispatch_message(self, message, eye: str):
        """
        Dispatches a message to the appropriate queue based on its content.
        """
        try:
            if isinstance(message, dict):
                if "payload" == message.get("type"):
                    self.sync_frames(message, eye)                 
                else:
                    self.health_monitor.failure("QueueHandler", f"Missing 'payload' in message from response loop.from eye: {eye}")
                    print("[WARN] QueueHandler: Missing 'payload' in message.")
            
            elif isinstance(message, bytes):
                self.tcp_server.send(
                    {
                        "category": "EyeloopData",
                        "eye": eye,
                        "payload": "PNG"
                    }, data_type="JSON", priority="medium")
                self.tcp_server.send(message, data_type="PNG", priority="medium")
            else:
                self.health_monitor.failure("QueueHandler", f"Unexpected message format: {type(message)}, content: {str(message)[:100]}")
                print(f"[WARN] QueueHandler: Unexpected message format: {type(message)}, content: {str(message)[:100]}")
        except Exception as e:
            self.health_monitor.failure("QueueHandler", f"Dispatch error (Left): {e}")
            print(f"[WARN] QueueHandler: Dispatch error {eye}: {e}")

    def sync_frames(self, message: dict, eye: str):
        """
        Synchronizes frames between the left and right EyeLoop processes.
        """

        payload = message.get("payload")
        data = message.get("data")
        if eye == "Left":
            if not isinstance(data, dict):
                self.health_monitor.failure("QueueHandler", "Invalid message format in sync_frames")
                print("[WARN] QueueHandler: Invalid message format in sync_frames")
                return
            self.frame_id_left = message.get("frame_id")
            self.message_left = data
        elif eye == "Right":
            if not isinstance(data, dict):
                self.health_monitor.failure("QueueHandler", "Invalid message format in sync_frames")
                print("[WARN] QueueHandler: Invalid message format in sync_frames")
                return
            self.frame_id_right = message.get("frame_id")
            self.message_right = data
        else:
            self.health_monitor.failure("QueueHandler", f"Invalid eye specified when syncing frames: {eye}")
            print(f"[WARN] QueueHandler: Invalid eye specified when syncing frames: {eye}")
            return

        if self.frame_id_left is not None and self.frame_id_right is not None:
            if self.frame_id_left == self.frame_id_right:
                # Both frames are synchronized
                if getattr(self.tracker_center, "setup_mode", True):
                    # In setup mode, send the frames to the TCP server
                    self.tcp_server.send(
                    {
                        "category": "EyeloopData",
                        "eye": "Left",
                        "payload": self.message_left
                    }, data_type="JSON", priority="medium")
                    self.tcp_server.send(
                    {
                        "category": "EyeloopData",
                        "eye": "Right",
                        "payload": self.message_right
                    }, data_type="JSON", priority="medium")
                    print(f"[INFO] QueueHandler: Sending synchronized frames with id {self.frame_id_left} to TCP server")
                    print(f"[DATA] QueueHandler: {self.message_left} ; {self.message_right}")
                else:
                    # Frames will be sent to post-processing later
                    #print("[INFO] QueueHandler: Frames will be sent to post-processing later")
                    print(f"[DATA] QueueHandler: {self.message_left} ; {self.message_right}")
                    pass

                self.frame_id_left = None
                self.frame_id_right = None
                self.message_left = None
                self.message_right = None

    def detach_eyeloop_memory(self, eye: str):
        """
        Detaches the EyeLoop process from the shared memory.
        """
        if eye == "L":
            self.send_command({"type": "detach"}, eye=eye)
        elif eye == "R":
            self.send_command({"type": "detach"}, eye=eye)
        else:
            self.health_monitor.failure("QueueHandler", f"Invalid eye specified when detaching memory: {eye}")
            print(f"[WARN] QueueHandler: Invalid eye specified when detaching memory: {eye}")

    def update_eyeloop_memory(self, eye: str):
        """
        Updates the EyeLoop process with the new memory configuration.
        """
        if eye == "L":
            self.send_command(
            {
                "type": "memory",
                "frame_shape": tracker_config.memory_shape_L,
                "frame_dtype": tracker_config.memory_dtype
            }, eye=eye)

        elif eye == "R":
            self.send_command(
            {
                "type": "memory",
                "frame_shape": tracker_config.memory_shape_R,
                "frame_dtype": tracker_config.memory_dtype
            }, eye=eye)
        else:
            self.health_monitor.failure("QueueHandler", f"Invalid eye specified when sending memory data to Eyeloop: {eye}")
            print(f"[WARN] QueueHandler: Invalid eye specified when sending memory data to Eyeloop: {eye}")

    def update_eyeloop_autosearch(self, autosearch):
        """
        Updates the EyeLoop process with the new autosearch configuration.
        """

        self.send_command(
        {
            "type": "config",
            "param": "auto_search",
            "value": autosearch
        }, eye="L")
        self.send_command(
        {
            "type": "config",
            "param": "auto_search",
            "value": autosearch
        }, eye="R")
        
    def close_eyeloop(self):
        """
        Closes the EyeLoop process and cleans up resources.
        """
        self.send_command({"type": "close"}, eye="L")
        self.send_command({"type": "close"}, eye="R")
        