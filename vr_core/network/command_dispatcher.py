import vr_core.config as Config
import vr_core.module_list as module_list 
import time
import threading

class CommandDispatcher:
    def __init__(self):

        module_list.command_dispatcher = self  # Register the command dispatcher in the module list

        self.camera_manager = None
        self.tcp_server = None  # Initialize TCP server instance
        self.tracker_center = None  # Initialize eye tracker centre instance
        self.queue_handler = None

        threading.Thread(target=self.components_manager, daemon=True).start()


    def components_manager(self):

        while True:
            time.sleep(1)

            if module_list.camera_manager != None and self.camera_manager == None:
                self.camera_manager = module_list.camera_manager
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "CameraManager is online.",
                    }, data_type="JSON", priority="low")
                print("[INFO] CommandDispatcher: CameraManager is online.")
            elif module_list.camera_manager == None and self.camera_manager != None:
                self.camera_manager = None
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "CameraManager went offline.",
                    }, data_type="JSON", priority="low")
                print("[WARN] CommandDispatcher: CameraManager went offline.")

            if module_list.tcp_server != None and self.tcp_server == None:
                self.tcp_server = module_list.tcp_server
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "TCPServer is online.",
                    }, data_type="JSON", priority="low")
                print("[INFO] CommandDispatcher: TCPServer is online.")
            elif module_list.tcp_server == None and self.tcp_server != None:
                self.tcp_server = None
                self.tcp_server.send(   
                    {
                        "type": "STATUS",
                        "data": "TCPServer went offline.",
                    }, data_type="JSON", priority="low")
                print("[WARN] CommandDispatcher: TCPServer went offline.")

            if module_list.tracker_center != None and self.tracker_center == None:
                self.tracker_center = module_list.tracker_center
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "TrackerCenter is online.",
                    }, data_type="JSON", priority="low")
                print("[INFO] CommandDispatcher: TrackerCenter is online.")
            elif module_list.tracker_center == None and self.tracker_center != None:
                self.tracker_center = None
                self.tcp_server.send(  
                    {
                        "type": "STATUS",
                        "data": "TrackerCenter went offline.",
                    }, data_type="JSON", priority="low")
                print("[WARN] CommandDispatcher: TrackerCenter went offline.")

            if module_list.queue_handler != None and self.queue_handler == None:   
                self.queue_handler = module_list.queue_handler
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "QueueHandler is online.",
                    }, data_type="JSON", priority="low")
                print("[INFO] CommandDispatcher: QueueHandler is online.")
            elif module_list.queue_handler == None and self.queue_handler != None:
                self.queue_handler = None
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "QueueHandler went offline.",
                    }, data_type="JSON", priority="low")
                print("[WARN] CommandDispatcher: QueueHandler went offline.")


    def handle_message(self, command_msg: dict):
        category = command_msg.get("category")
        action = command_msg.get("action")
        params = command_msg.get("params", {})

        if category == "eye_tracker":
            self._handle_eyeloop_action(action, params)
        elif category == "tracker_mode":
            self._handle_eye_tracker_action(action, params)
        elif category == "config":
            self._handle_config_action(action, params)
        else:
            print(f"[WARN] CommandDispatcher: Unknown command category: {category}")


    def _handle_eyeloop_action(self, action, params):
        if self.queue_handler is not None:
            self.queue_handler.send_command(action, params, action)
        else:    
            self.tcp_server.send(
                {
                    "type": "STATUS",
                    "data": "QueueHandler is offline.",
                }, data_type="JSON", priority="low"
            )
            print("[WARN] CommandDispatcher: QueueHandler not connected. Cannot handle action.")
            return


    def _handle_eye_tracker_action(self, action, params):
        if self.tracker_center is not None:
            if action == "setup_tracker_1":
                self.tracker_center.handle_command(action)
            elif action == "setup_tracker_2":
                self.tracker_center.handle_command(action)
            elif action == "launch_tracker":
                self.tracker_center.handle_command(action)
            else:
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": f"Unknown action '{action}' for TrackerCenter.",
                    }, data_type="JSON", priority="low"
                )
                print(f"[WARN] CommandDispatcher: Unknown tracker_center mode: {action}")
        else:
            self.tcp_server.send(
                {
                    "type": "STATUS",
                    "data": "TrackerCenter is offline.",
                }, data_type="JSON", priority="low"
            )
            print("[WARN] CommandDispatcher: TrackerCenter not connected. Cannot handle action.")

    def _handle_config_action(self, action, params):
        try:
            class_name, attr_name = action.split()
            config_class = getattr(Config, class_name)
            if hasattr(config_class, attr_name):
                setattr(config_class, attr_name, params)
                if class_name == "CameraManagerConfig":
                    if self.camera_manager is not None:
                        self.camera_manager.apply_config()
                    else:
                        self.tcp_server.send(
                            {
                                "type": "STATUS",
                                "data": "CameraManager is offline.",
                            }, data_type="JSON", priority="low"
                        )
                        print("[WARN] Config: CameraManager not initialized. Camera settings not applied.")

                print(f"[Config] {class_name}.{attr_name} set to {params}")
            else:
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": f"Unknown attribute '{attr_name}' in {class_name}.",
                    }, data_type="JSON", priority="low"
                )
                print(f"[WARN] Config: Unknown attribute '{attr_name}' in {class_name}")
        except ValueError:
            self.tcp_server.send(
                {
                    "type": "STATUS",
                    "data": f"Invalid action format: '{action}'. Expected 'ClassName attribute' format.",
                }, data_type="JSON", priority="low"
            )
            print(f"[WARN] Config: Invalid action format: '{action}'. Expected 'ClassName attribute' format.")
        except AttributeError:
            self.tcp_server.send(
                {
                    "type": "STATUS",
                    "data": f"Unknown configuration class: '{class_name}'.",
                }, data_type="JSON", priority="low"
            )
            print(f"[WARN] Config: Unknown configuration class: '{class_name}'")

