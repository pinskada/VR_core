import vr_core.config as Config
import vr_core.module_list as module_list 
import time
import threading

class CommandDispatcher:
    def __init__(self):

        module_list.command_dispatcher = self  # Register the command dispatcher in the module list

        self.camera_manager = None
        self.esp32 = None  # Initialize ESP32 instance
        self.gyroscope = None  # Initialize gyroscope instance

        self.tcp_server = None  # Initialize TCP server instance
        
        self.tracker_center = None  # Initialize eye tracker centre instance
        self.queue_handler = None
        self.frame_provider = None  # Initialize frame provider instance
        self.tracker_launcher = None  # Initialize tracker launcher instance


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

