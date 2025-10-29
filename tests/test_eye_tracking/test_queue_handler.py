import unittest
from unittest.mock import MagicMock, patch
from multiprocessing import Queue
import vr_core.module_list as module_list
from vr_core.eye_tracker.tracker_sync import QueueHandler


class TestQueueHandler(unittest.TestCase):
    def setUp(self):
        # Mocks to replace dependencies in module_list
        self.mock_tcp_server = MagicMock()
        self.mock_health_monitor = MagicMock()
        self.mock_tracker_center = MagicMock()
        self.mock_tracker_center.setup_mode = True  # simulate preview mode

        module_list.tcp_server = self.mock_tcp_server
        module_list.health_monitor = self.mock_health_monitor
        module_list.tracker_center = self.mock_tracker_center

        # Patch TrackerConfig temporarily for queue timeout
        patcher = patch("vr_core.config.TrackerConfig.queue_timeout", 0.1)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_command_and_response_flow(self):
        handler = QueueHandler()

        # Test: command sending
        handler.send_command("test_cmd", "L")
        self.assertEqual(handler.command_queue_L.get(timeout=0.1), "test_cmd")

        handler.send_command("test_cmd", "R")
        self.assertEqual(handler.command_queue_R.get(timeout=0.1), "test_cmd")

        # Test: dispatch dict payload and sync
        test_msg = {"payload": {"frame_id": 1, "data": "eye data"}}
        handler.dispatch_message(test_msg, "L")
        handler.dispatch_message(test_msg, "R")

        self.mock_tcp_server.send.assert_any_call(
            {
                "category": "EyeloopData",
                "eye": "L",
                "payload": {"frame_id": 1, "data": "eye data"},
            },
            data_type="JSON",
            priority="medium"
        )

        self.mock_tcp_server.send.assert_any_call(
            {
                "category": "EyeloopData",
                "eye": "R",
                "payload": {"frame_id": 1, "data": "eye data"},
            },
            data_type="JSON",
            priority="medium"
        )

        # Test: dispatch binary (bytes) message
        handler.dispatch_message(b"\x89PNG...", "L")
        self.mock_tcp_server.send.assert_any_call(
            {
                "category": "EyeloopData",
                "eye": "L",
                "payload": "PNG"
            },
            data_type="JSON",
            priority="medium"
        )

    def test_invalid_dispatch(self):
        handler = QueueHandler()
        handler.dispatch_message("unexpected_string", "L")
        self.mock_health_monitor.failure.assert_called()


if __name__ == "__main__":
    unittest.main()
