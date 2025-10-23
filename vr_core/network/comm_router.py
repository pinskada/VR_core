"""Communicatrion router between modules and TCP server."""

import time
import queue
import threading

import vr_core.config as Config
import vr_core.module_list as module_list
from vr_core.eye_tracker.tracker_control import TrackerCenter
#from vr_core.raspberry_perif.camera_manager import CameraManager


class CommandDispatcher:
    """Command dispatcher for routing commands between modules and TCP server."""
    def __init__(self):
        self.online = True

        module_list.command_dispatcher = self  # Register the command dispatcher in the module list

        module_list.cmd_dispatcher_queue = queue.Queue()

        self.handle_message_thread = threading.Thread(target=self.handle_message)
        self.handle_message_thread.start() # Start the frame provider

    def handle_message(self):
        """Handle incoming messages from the command dispatcher queue."""
        while self.online:

            try:
                if module_list.cmd_dispatcher_queue:
                    command_msg = module_list.cmd_dispatcher_queue.get(timeout=0.005)
                else:
                    print("[WARN] CommandDispatcher: cmd_dispatcher_queue not initialized.")
                    continue

                category = command_msg.get("category")
                action = command_msg.get("action")
                try:
                    params = command_msg.get("params", {})
                except Exception:
                    pass

                print(f"[INFO] CommandDispatcher: Message inbound; Category: {category}")

                if category == "eye_tracker":
                    self._handle_eyeloop_action(action, params)
                elif category == "tracker_mode":
                    self._handle_eye_tracker_action(action)
                elif category == "calibration":
                    self._handle_calibration_action(action)
                elif category == "config":
                    self._handle_config_action(action, params)
                else:
                    print(f"[WARN] CommandDispatcher: Unknown command category: {category}")
            except Exception as e:
                pass

    def _handle_eyeloop_action(self, action, params):
        """Handle eyeloop related actions."""
        if module_list.queue_handler is not None:
            module_list.queue_handler.send_command(params, action)
        else:
            if module_list.tcp_server:
                module_list.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "QueueHandler is offline.",
                    }, data_type="JSON", priority="low"
                )
            print("[WARN] CommandDispatcher: QueueHandler not connected. Cannot handle action.")
            return


    def _handle_eye_tracker_action(self, action):
        """Handle eye tracker related actions."""
        if action == "setup_tracker_1":
            self.kill_eyetracker()
            print("[INFO] CommandDispatcher: Starting setup_tracker_1.")

            Config.tracker_config.sync_timeout = 5
            if not Config.tracker_config.use_test_video:
                if module_list.cam_manager:
                    module_list.cam_manager.start_camera()
            module_list.tracker_center = TrackerCenter()
            module_list.tracker_center.setup_tracker_1()
        elif action == "setup_tracker_2":
            self.kill_eyetracker()
            print("[INFO] CommandDispatcher: Starting setup_tracker_2.")

            Config.tracker_config.sync_timeout = 2
            if not Config.tracker_config.use_test_video:
                if module_list.cam_manager:
                    module_list.cam_manager.start_camera()
            module_list.tracker_center = TrackerCenter()
            module_list.tracker_center.setup_tracker_2()
        elif action == "launch_tracker":
            self.kill_eyetracker()
            print("[INFO] CommandDispatcher: Starting launch_tracker.")

            Config.tracker_config.sync_timeout = 2
            if not Config.tracker_config.use_test_video:
                if module_list.cam_manager:
                    module_list.cam_manager.start_camera()
            module_list.tracker_center = TrackerCenter()
            module_list.tracker_center.launch_tracker()
        elif action == "stop_preview":
            self.kill_eyetracker()
            Config.tracker_config.sync_timeout = 10
        else:
            if module_list.tcp_server:
                module_list.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": f"Unknown action '{action}' for TrackerCenter.",
                    }, data_type="JSON", priority="low"
                )
            print(f"[WARN] CommandDispatcher: Unknown tracker_center mode: {action}")

    def _handle_calibration_action(self, action):
        """Handle calibration related actions."""
        if module_list.calibration_handler:
            if action == "start_calibration":
                module_list.calibration_handler.start_calibration()
            elif action == "stop_calibration":
                module_list.calibration_handler.stop_calibration()
            elif action == "start_processing":
                module_list.calibration_handler.start_processing()
            elif action == "stop_processing":
                module_list.calibration_handler.stop_processing()
            else:
                if module_list.tcp_server:
                    module_list.tcp_server.send(
                        {
                            "type": "STATUS",
                            "data": f"Unknown action '{action}' for CalibrationHandler.",
                        }, data_type="JSON", priority="low"
                    )
                print(f"[WARN] CommandDispatcher: Unknown calibration action: {action}")
        else:
            if module_list.tcp_server:
                module_list.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": "CalibrationHandler is offline.",
                    }, data_type="JSON", priority="low"
                )
            print("[WARN] CommandDispatcher: CalibrationHandler"
                  "not connected. Cannot handle action.")

    def _handle_config_action(self, action, params):
        """Handle configuration related actions."""
        try:
            class_name, attr_name = action.split()
            config_class = getattr(Config, class_name)

            if hasattr(config_class, attr_name):
                if attr_name.startswith("crop_"):
                    params = (tuple(params[0]), tuple(params[1]))
                    setattr(config_class, attr_name, params)
                else:
                    setattr(config_class, attr_name, float(params))

                print(f"[Config] {class_name}.{attr_name} set to {params}")
            else:
                if module_list.tcp_server:
                    module_list.tcp_server.send(
                        {
                            "type": "STATUS",
                            "data": f"Unknown attribute '{attr_name}' in {class_name}.",
                        }, data_type="JSON", priority="low"
                    )
                print(f"[WARN] Config: Unknown attribute '{attr_name}' in {class_name}")

            if class_name == "camera_manager_config":
                if module_list.cam_manager:
                    #module_list.cam_manager.stop_camera
                    #time.sleep(0.1)
                    module_list.cam_manager.start_camera()
                else:
                    if module_list.tcp_server:
                        module_list.tcp_server.send(
                            {
                                "type": "STATUS",
                                "data": "CameraManager is offline.",
                            }, data_type="JSON", priority="low"
                        )
                    print("[WARN] Config: CameraManager not initialized. "
                          "Camera settings not applied.")
        except ValueError:
            if module_list.tcp_server:
                module_list.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": f"Invalid action format: '{action}'. "
                        "Expected 'ClassName attribute' format.",
                    }, data_type="JSON", priority="low"
                )
            print(f"[WARN] Config: Invalid action format: '{action}'. "
                  "Expected 'ClassName attribute' format.")
        except AttributeError:
            if module_list.tcp_server:
                module_list.tcp_server.send(
                    {
                        "type": "STATUS",
                        "data": f"Unknown configuration class: '{class_name}'.",
                    }, data_type="JSON", priority="low"
                )

            print(f"[WARN] Config: Unknown configuration class: '{class_name}'")

    def kill_eyetracker(self):
        """Terminate the eye tracker and clean up resources."""
        try:
            if module_list.tracker_center:
                module_list.tracker_center.stop_preview()
        except:
            pass

        module_list.tracker_center = None
        try:
            if module_list.queue_handler:
                module_list.queue_handler.stop()
        except Exception as e:
            pass
        try:
            if module_list.cam_manager:
                module_list.cam_manager.stop_camera()
        except:
            pass
        module_list.queue_handler = None
        module_list.tracker_launcher = None

        print("[INFO] CommandDispatcher: All resources clean.")

        time.sleep(0.1)

    def is_online(self):
        """Check if the command dispatcher is online."""
        return self.online
