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
        self.pre_processor = module_list.pre_processor  # Reference to the pre-processor module

        self.frame_id_left = None
        self.frame_id_right = None

        self.png_id_left = 0
        self.png_id_right = 0

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
            self.response_thread_left = threading.Thread(target=self._response_loop_left)
            self.response_thread_right = threading.Thread(target=self._response_loop_right)

            self.response_thread_left.start()
            self.response_thread_right.start()
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
        return self.sync_queue_L, self.sync_queue_R
    
    def get_ack_queues(self):
        return self.acknowledge_queue_L, self.acknowledge_queue_R
    
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


    def _response_loop_left(self):
        while self.online:
            try:
                msg_L = self.response_queue_L.get(timeout=tracker_config.handler_queue_timeout)
                self.dispatch_message(msg_L, "Left")

            except Exception:
                # Silently skip if queues are empty or error occurs
                #time.sleep(tracker_config.handler_queue_timeout)
                pass

    def _response_loop_right(self):
        while self.online:
            try:
                msg_R = self.response_queue_R.get(timeout=tracker_config.handler_queue_timeout)
                self.dispatch_message(msg_R, "Right")

            except Exception:
                # Silently skip if queues are empty or error occurs
                #time.sleep(tracker_config.handler_queue_timeout)
                pass

    def dispatch_message(self, message, eye: str):
        """
        Dispatches a message to the appropriate queue based on its content.
        """
        
        try:
            if isinstance(message, dict):
                if "payload" == message.get("type"):
                    if message.get("data"):
                        self.sync_frames(message, eye)          
                else:
                    self.health_monitor.failure("QueueHandler", f"Missing 'payload' in message from response loop.from eye: {eye}")
                    print("[WARN] QueueHandler: Missing 'payload' in message.")
            
            elif isinstance(message, bytes):
                if eye == "Left":
                    self.png_id_left += 1
                else:
                    self.png_id_right += 1

                send_left = self.png_id_left % tracker_config.png_send_rate == 0
                send_right = (self.png_id_right + round(tracker_config.png_send_rate / 2)) % tracker_config.png_send_rate == 0

                if send_left and eye == "Left":
                    self.tcp_server.send(
                        {
                            "type": "imageInfo",
                            "data": f"{eye}"
                        }, data_type="JSON", priority="medium")
                    time.sleep(0.1)
                    self.tcp_server.send(message, data_type="PNG", priority="medium")
                    time.sleep(0.1)
                    self.png_id_left = 0
                    #print(f"[INFO] QueueHandler: Sending {eye} eye PNG preview to client")
                elif send_right and eye == "Right":
                    self.tcp_server.send(
                        {
                            "type": "imageInfo",
                            "data": f"{eye}"
                        }, data_type="JSON", priority="medium")
                    time.sleep(0.1)
                    self.tcp_server.send(message, data_type="PNG", priority="medium")
                    time.sleep(0.1)
                    self.png_id_right = 0
                    #print(f"[INFO] QueueHandler: Sending {eye} eye PNG preview to client")
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
            #print(f"[INFO] QueueHandler: Received left frame with id {self.frame_id_left}")
        elif eye == "Right":
            if not isinstance(data, dict):
                self.health_monitor.failure("QueueHandler", "Invalid message format in sync_frames")
                print("[WARN] QueueHandler: Invalid message format in sync_frames")
                return
            self.frame_id_right = message.get("frame_id")
            self.message_right = data
            #print(f"[INFO] QueueHandler: Received right frame with id {self.frame_id_right}")
        else:
            self.health_monitor.failure("QueueHandler", f"Invalid eye specified when syncing frames: {eye}")
            #print(f"[WARN] QueueHandler: Invalid eye specified when syncing frames: {eye}")
            return

        if self.frame_id_left is not None and self.frame_id_right is not None:
            if self.frame_id_left == self.frame_id_right:
                # Both frames are synchronized
                if getattr(self.tracker_center, "setup_mode", True):
                    # In setup mode, send the frames to the TCP server
  
                    self.pre_processor.get_relative_ipd(self.message_left, self.message_right)
                    print("Good to go")
                else:
                    self.pre_processor.get_relative_ipd(self.message_left, self.message_right)
                    print("Good to go")

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

    def prompt_preview(self, send_preview):
        """
        Updates Eyeloop whether to send preview.
        """
        self.send_command(
        {
            "type": "config",
            "param": "preview",
            "value": send_preview
        }, eye="L")
        self.send_command(
        {
            "type": "config",
            "param": "preview",
            "value": send_preview
        }, eye="R")

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
        
    def stop(self):
        self.online = False
        self.command_queue_L.close()
        self.command_queue_R.close()
        self.response_queue_L.close()
        self.response_queue_R.close()
        self.sync_queue_L.close()
        self.sync_queue_R.close()
        self.acknowledge_queue_L.close()
        self.acknowledge_queue_R.close()
        time.sleep(0.1)
        self.response_thread_right.join()
        self.response_thread_left.join()