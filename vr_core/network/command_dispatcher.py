import vr_core.config as Config
import vr_core.module_list as module_list 

class CommandDispatcher:
    def __init__(self):

        module_list.command_dispatcher = self  # Register the command dispatcher in the module list
        self.tcp_server = module_list.tcp_server  # Access the TCP server from the module list

    def handle_message(self, command_msg: dict):
        category = command_msg.get("category")
        action = command_msg.get("action")
        params = command_msg.get("params", {})

        if category == "eye_tracker":
            self._handle_eyeloop_action(action, params)
        elif category == "tracker_mode":
            self._handle_eye_tracker_action(action)
        elif category == "config":
            self._handle_config_action(action, params)
        else:
            print(f"[WARN] CommandDispatcher: Unknown command category: {category}")


    def _handle_eyeloop_action(self, action, params):
        if module_list.queue_handler is not None:
            module_list.queue_handler.send_command(params, action)
        else:    
            self.tcp_server.send(
                {
                    "type": "STATUS",
                    "data": "QueueHandler is offline.",
                }, data_type="JSON", priority="low"
            )
            print("[WARN] CommandDispatcher: QueueHandler not connected. Cannot handle action.")
            return


    def _handle_eye_tracker_action(self, action):
        if module_list.tracker_center is not None:
            if action == "setup_tracker_1":
                module_list.tracker_center.setup_tracker_1()
            elif action == "setup_tracker_2":
                module_list.tracker_center.setup_tracker_2()
            elif action == "launch_tracker":
                module_list.tracker_center.launch_tracker()
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

                if class_name == "camera_manager_config":
                    if module_list.camera_manager is not None:
                        module_list.camera_manager.apply_config()
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

