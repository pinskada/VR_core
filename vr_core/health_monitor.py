import vr_core.module_list as module_list
import threading


class HealthMonitor:
    def __init__(self):
        module_list.health_monitor = self
        self.tcp_server = module_list.tcp_server
        threading.Thread(target=self.check_health, daemon=True).start()

    def check_health(self):
        """Periodically checks the health status of all components."""
        while True:
            pass


    def failure(self, component_name=str, status=str):
        """Handles failure of a component."""
        self.tcp_server.send(
            {
                "type": "FAILURE",
                "data": f"{component_name}: {status}",
            }, data_type="JSON", priority="low")
