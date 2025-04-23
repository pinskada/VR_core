import vr_core.module_list as module_list
from vr_core.config import HealthMonitorConfig
import threading
import time

class HealthMonitor:
    def __init__(self):
        module_list.health_monitor = self
        self.tcp_server = module_list.tcp_server
        self.component_status = {}
        print("[INFO] HealthMonitor: Health monitoring thread started.")
        self.tcp_server.send( 
            {
                "type": "STATUS",
                "data": "HealthMonitor: Health monitoring thread started.",
            }, data_type="JSON", priority="low")
        threading.Thread(target=self.check_for_health, daemon=True).start()

    def check_for_health(self):
        """
        Periodically checks the online status of all known components except EyeTrackerCenter.
        Sends updates to Unity if any component changes status.
        """
        monitored_components = {
            "Gyroscope": module_list.gyroscope,
            "ESP32": module_list.esp32,
            "CameraConfig": module_list.camera_manager,
            "QueueHandler": module_list.queue_handler,
            "FrameProvider": module_list.frame_provider,
            "TrackerHandler": module_list.tracker_launcher
        }

        while True:
            for name, component in monitored_components.items():
                if component is None:
                    continue

                is_online = component.is_online()
                previous = self.component_status.get(name)

                if previous is None or previous != is_online:
                    status_str = "went offline" if not is_online else "came online"
                    print(f"[HealthMonitor] {name} {status_str}.")

                    self.tcp_server.send({
                        "type": "STATUS",
                        "data": f"{name} {status_str}"
                    }, data_type="JSON", priority="low")

                    self.component_status[name] = is_online

            time.sleep(HealthMonitorConfig.check_interval)

    def status(self, component_name: str, status: str):
        """Handles status updates of a component."""
        self.tcp_server.send(
            {
                "type": "STATUS",
                "data": f"{component_name}: {status}",
            }, data_type="JSON", priority="low")

    def failure(self, component_name: str, status: str):
        """Handles failure update of a component."""
        self.tcp_server.send(
            {
                "type": "FAILURE",
                "data": f"{component_name}: {status}",
            }, data_type="JSON", priority="low")
