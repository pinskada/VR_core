from multiprocessing import Queue


class EyeLoopQueueHandler:
    def __init__(self):
        """
        Contains the command and response queues for the EyeLoop processes.
        This class is used to manage the communication between the EyeLoop processes and the main process.
        """

        self.command_queue_L = Queue()
        self.command_queue_R = Queue()
        self.response_queue_L = Queue()
        self.response_queue_R = Queue()
        self.sync_queue_L = Queue()
        self.sync_queue_R = Queue()
    

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
    
    def get_response(self, eye: str):
        """
        Retrieves a response from the specified EyeLoop process.
        """
        if eye == "L":
            return self.response_queue_L.get()
        elif eye == "R":
            return self.response_queue_R.get()
        else:
            raise ValueError("Invalid eye specified. Use 'L' or 'R'.")
