import vr_core.config as Config
from vr_core.raspberry_perif.camera_config import CameraConfigManager
import vr_core.module_list as module_list 
import time
import threading

class CommandDispatcher:
    def __init__(self):

        module_list.command_dispatcher = self  # Register the command dispatcher in the module list

        self.camera_config_manager = None
        self.tcp_server = None  # Initialize TCP server instance
        self.eye_tracker_centre = None  # Initialize eye tracker centre instance
        self.eyeloop_queue_handler = None

        threading.Thread(target=self.components_manager, daemon=True).start()


    def components_manager(self):

        while True:
            time.sleep(1)

            if module_list.camera_config_manager != None and self.camera_config_manager == None:
                self.camera_config_manager = module_list.camera_config_manager
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "CameraConfigManager is online.",
                    }, data_type="JSON", priority="low")
                print("[CommandDispatcher] CameraConfigManager is online.")
            elif module_list.camera_config_manager == None and self.camera_config_manager != None:
                self.camera_config_manager = None
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "CameraConfigManager went offline.",
                    }, data_type="JSON", priority="low")

            if module_list.tcp_server != None and self.tcp_server == None:
                self.tcp_server = module_list.tcp_server
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "TCPServer is online.",
                    }, data_type="JSON", priority="low")
                print("[CommandDispatcher] TCPServer is online.")
            elif module_list.tcp_server == None and self.tcp_server != None:
                self.tcp_server = None
                self.tcp_server.send(   
                    {
                        "type": "STATUS",
                        "data": "TCPServer went offline.",
                    }, data_type="JSON", priority="low")
                print("[CommandDispatcher] TCPServer went offline.")

            if module_list.eye_tracker_centre != None and self.eye_tracker_centre == None:
                self.eye_tracker_centre = module_list.eye_tracker_centre
                print("[CommandDispatcher] EyeTrackerCentre is online.")
            elif module_list.eye_tracker_centre == None and self.eye_tracker_centre != None:
                self.eye_tracker_centre = None
                self.tcp_server.send(  
                    {
                        "type": "STATUS",
                        "data": "EyeTrackerCentre went offline.",
                    }, data_type="JSON", priority="low")
                print("[CommandDispatcher] EyeTrackerCentre went offline.")

            if module_list.eyeloop_queue_handler != None and self.eyeloop_queue_handler == None:   
                self.eyeloop_queue_handler = module_list.eyeloop_queue_handler
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "EyeLoopQueueHandler is online.",
                    }, data_type="JSON", priority="low")
                print("[CommandDispatcher] EyeLoopQueueHandler is online.")
            elif module_list.eyeloop_queue_handler == None and self.eyeloop_queue_handler != None:
                self.eyeloop_queue_handler = None
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "EyeLoopQueueHandler went offline.",
                    }, data_type="JSON", priority="low")
                print("[CommandDispatcher] EyeLoopQueueHandler went offline.")


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
            print(f"[CommandDispatcher] Unknown command category: {category}")


    def _handle_eyeloop_action(self, action, params):
        if self.eyeloop_queue_handler is not None:
            self.eyeloop_queue_handler.send_command(action, params, action)
        else:    
            self.tcp_server.send(
                {
                    "type": "STATUS",
                    "data": "EyeLoopQueueHandler is offline.",
                }, data_type="JSON", priority="low"
            )
            print("[CommandDispatcher] EyeLoopQueueHandler not connected. Cannot handle action.")
            return


    def _handle_eye_tracker_action(self, action, params):
        if self.eye_tracker_centre is not None:
            if action == "setup_tracker_1":
                self.eye_tracker_centre.handle_command(action)
            elif action == "setup_tracker_2":
                self.eye_tracker_centre.handle_command(action)
            elif action == "launch_tracker":
                self.eye_tracker_centre.handle_command(action)
            else:
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": f"Unknown action '{action}' for EyeTrackerCentre.",
                    }, data_type="JSON", priority="low"
                )
                print(f"[CommandDispatcher] Unknown tracker_mode mode: {action}")
        else:
            self.tcp_server.send(
                {
                    "type": "STATUS",
                    "data": "EyeTrackerCentre is offline.",
                }, data_type="JSON", priority="low"
            )
            print("[CommandDispatcher] EyeTrackerCentre not connected. Cannot handle action.")

    def _handle_config_action(self, action, params):
        try:
            class_name, attr_name = action.split()
            config_class = getattr(Config, class_name)
            if hasattr(config_class, attr_name):
                setattr(config_class, attr_name, params)
                if class_name == "CameraConfig":
                    if self.camera_config_manager is not None:
                        self.camera_config_manager.apply_config()
                    else:
                        self.tcp_server.send(
                            {
                                "type": "STATUS",
                                "data": "CameraConfigManager is offline.",
                            }, data_type="JSON", priority="low"
                        )
                        print("[Config] CameraConfigManager not initialized. Camera settings not applied.")

                print(f"[Config] {class_name}.{attr_name} set to {params}")
            else:
                self.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": f"Unknown attribute '{attr_name}' in {class_name}.",
                    }, data_type="JSON", priority="low"
                )
                print(f"[Config] Unknown attribute '{attr_name}' in {class_name}")
        except ValueError:
            self.tcp_server.send(
                {
                    "type": "STATUS",
                    "data": f"Invalid action format: '{action}'. Expected 'ClassName attribute' format.",
                }, data_type="JSON", priority="low"
            )
            print(f"[Config] Invalid action format: '{action}'. Expected 'ClassName attribute' format.")
        except AttributeError:
            self.tcp_server.send(
                {
                    "type": "STATUS",
                    "data": f"Unknown configuration class: '{class_name}'.",
                }, data_type="JSON", priority="low"
            )
            print(f"[Config] Unknown configuration class: '{class_name}'")

