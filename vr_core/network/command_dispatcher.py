import vr_core.config as Config
from vr_core.raspberry_perif.camera_config import CameraConfigManager

class CommandDispatcher:
    def __init__(self, tcp_server):
        self.tcp_server = tcp_server

        self.tcp_server.set_command_dispatcher(self)  # Set the command dispatcher for the TCP server
    
        self.camera_config_manager = None
        self.eye_tracker_centre = None
        self.eyeloop_queue_handler = None
        self.tracker_handler = None
        self.frame_provider = None

    def handle(self, command_msg: dict):
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
            print(f"[CommandDispatcher] Unknown command category: {category}")


    def _handle_eyeloop_action(self, action, params):
        self.eyeloop_queue_handler.send_command(action, params, action)


    def _handle_eye_tracker_action(self, action, params):
        if action == "setup_tracker_1":
            self.eye_tracker_centre.handle_command(action)
        elif action == "setup_tracker_2":
            self.eye_tracker_centre.handle_command(action)
        elif action == "launch_tracker":
            self.eye_tracker_centre.handle_command(action)
        else:
            print(f"[CommandDispatcher] Unknown tracker_mode mode: {action}")


    def _handle_config_action(self, action, params):
        try:
            class_name, attr_name = action.split()
            config_class = getattr(Config, class_name)
            if hasattr(config_class, attr_name):
                setattr(config_class, attr_name, params)
                if class_name == "CameraConfig":
                    try:
                        self.camera_config_manager.apply_config()
                    except:
                        print("[Config] CameraConfigManager not initialized. Camera settings not applied.")

                print(f"[Config] {class_name}.{attr_name} set to {params}")
            else:
                print(f"[Config] Unknown attribute '{attr_name}' in {class_name}")
        except ValueError:
            print(f"[Config] Invalid action format: '{action}'. Expected 'ClassName attribute' format.")
        except AttributeError:
            print(f"[Config] Unknown configuration class: '{class_name}'")

