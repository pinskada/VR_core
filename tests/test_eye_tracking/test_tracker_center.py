# test_tracker_center.py
import unittest
from unittest.mock import patch, MagicMock

from vr_core.eye_tracker.tracker_center import TrackerCenter


class TestTrackerCenter(unittest.TestCase):
    def test_tracker_center(self):
        print("\n=== Starting test_tracker_center ===")

        # Create mock components
        mock_tcp_server = MagicMock()
        mock_health_monitor = MagicMock()
        MockFrameProvider = MagicMock()
        MockTrackerLauncher = MagicMock()
        MockQueueHandler = MagicMock()

        # Setup return values for the mock queue handler
        mock_queue_handler_instance = MockQueueHandler.return_value
        mock_queue_handler_instance.get_command_queues.return_value = ("cmd_L", "cmd_R")
        mock_queue_handler_instance.get_response_queues.return_value = ("resp_L", "resp_R")
        mock_queue_handler_instance.get_sync_queues.return_value = ("sync_L", "sync_R")

        with patch('vr_core.eye_tracker.tracker_center.module_list.tcp_server', mock_tcp_server), \
             patch('vr_core.eye_tracker.tracker_center.module_list.health_monitor', mock_health_monitor), \
             patch('vr_core.eye_tracker.tracker_center.FrameProvider', MockFrameProvider), \
             patch('vr_core.eye_tracker.tracker_center.TrackerLauncher', MockTrackerLauncher), \
             patch('vr_core.eye_tracker.tracker_center.QueueHandler', MockQueueHandler):

            # Instantiate TrackerCenter
            etc = TrackerCenter(test_mode=True)

            # Check attribute setup
            self.assertEqual(etc.command_queue_L, "cmd_L")
            self.assertTrue(etc.frame_provider is None)
            self.assertTrue(etc.tracker_launcher is None)
            self.assertEqual(etc.queue_handler, mock_queue_handler_instance)


            # Simulate 'setup_tracker_1' command
            print("\n\n=== Simulating setup_tracker_1 command ===")
            etc.handle_command("setup_tracker_1")
            self.assertTrue(etc.setup_mode)
            MockFrameProvider.assert_called()
            self.assertTrue(etc.preview_thread.is_alive())
            etc.stop_preview()  # Stop the preview after setup

            # Simulate 'setup_tracker_2' command
            print("\n\n=== Simulating setup_tracker_2 command ===")
            etc.handle_command("setup_tracker_2")
            MockFrameProvider.assert_called()
            MockTrackerLauncher.assert_called()

            # Simulate 'launch_tracker' command
            print("\n\n=== Simulating launch_tracker command ===")
            etc.handle_command("launch_tracker")
            MockFrameProvider.assert_called()
            MockTrackerLauncher.assert_called()

            # Stop preview safely
            etc.stop_preview()
            self.assertFalse(etc.setup_mode)

        print("\n\n=== test_tracker_center PASSED ===")


if __name__ == "__main__":
    unittest.main()
