import vr_core.module_list as module_list
from vr_core.config import health_monitor
import threading
import time

class HealthMonitor:
    def __init__(self):
        module_list.health_monitor = self
        self.tcp_server = module_list.tcp_server

        self._stop_event = threading.Event()
        self._last_status = {}

         # Map of component names to instances
        self._monitored = {
            'Gyroscope': module_list.gyroscope,
            'ESP32': module_list.esp32,
            'CameraManager': module_list.camera_manager,
            'TrackerCenter': module_list.tracker_center,
            'QueueHandler': module_list.queue_handler,
            'FrameProvider': module_list.frame_provider,
            'TrackerLauncher': module_list.tracker_launcher,
            'TCPServer': module_list.tcp_server,
            'CommandDispatcher': module_list.command_dispatcher,
        }

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

        while True:
            for name, comp in self._monitored.items():
                # Determine current online status
                current = False
                if comp is not None and hasattr(comp, 'is_online'):
                    try:
                        current = bool(comp.is_online())
                    except Exception:
                        current = False

                previous = self._last_status.get(name)

                # First time seeing this component: record and move on
                if previous is None:
                    self._last_status[name] = current
                    continue

                # Detect transitions
                if not previous and current:
                    # Went from offline to online
                    status_str = 'ONLINE'
                elif previous and not current:
                    # Went from online to offline
                    status_str = 'OFFLINE'
                else:
                    # No change since last check
                    continue

                # Log the transition
                print(f"[HealthMonitor] {name} went {status_str}")

                # Notify over TCP if server provided
                if self.tcp_server:
                    self.tcp_server.send(
                        {
                            'type': 'STATUS',
                            'component': name,
                            'online': current
                        },
                        data_type='JSON',
                        priority='low'
                    )

                # Update stored state
                self._last_status[name] = current

            time.sleep(health_monitor.check_interval)

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
