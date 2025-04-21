from multiprocessing import Queue
import threading
import time
from vr_core.config import EyeTrackerConfig

class EyeLoopQueueHandler:
    """
    Contains the command and response queues for the EyeLoop processes.
    This class is used to manage the communication between the EyeLoop processes and the main process.
    """
    
    def __init__(self, eye_tracker_centre, tcp_server, command_dispatcher):

        self.command_dispatcher = command_dispatcher  # Command dispatcher for handling commands
        self.tcp_server = tcp_server  # Reference to the TCP server for communication
        self.eye_tracker_centre = eye_tracker_centre  # Reference to the EyeTrackerCentre instance

        self.command_dispatcher.eyeloop_queue_handler = self  # Set the command dispatcher to this instance

        # Initialize queues for both left and right EyeLoop processes
        self.command_queue_L = Queue()
        self.command_queue_R = Queue()
        self.response_queue_L = Queue()
        self.response_queue_R = Queue()
        self.sync_queue_L = Queue()
        self.sync_queue_R = Queue()

        self.online = True
        self.response_thread = threading.Thread(target=self._response_loop, daemon=True)
        self.response_thread.start()
 
        

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
      
        print(f"[QueueHandler] Sending command to {eye}: {command}")
        if eye == "L":
            self.command_queue_L.put(command)
        elif eye == "R":
            self.command_queue_R.put(command)
        else:
            raise ValueError("Invalid eye specified. Use 'L' or 'R'.")
    
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


    def dispatch_message(self, message: str, eye: str):
        """
        Dispatches a message to the appropriate queue based on its content.
        """
        category = message.get("category")
        if category == "Data":
            if self.eye_tracker_centre.setup_mode:
                self.tcp_server.send({"type": "EyeloopData", "eye": eye, "payload": message["payload"]}, priority="medium")
            else:
                ### Send data to the main process for processing
                pass

        elif category == "BinImage":
            self.tcp_server.send({"type": "BinPreview", "eye": eye, "payload": message["payload"]}, priority="medium")




