import time
from unittest.mock import MagicMock
from multiprocessing import Queue
from vr_core.eye_tracker.queue_handler import QueueHandler

def test_eyeloop_queue_handler():
    print("\n=== Starting test_eyeloop_queue_handler ===")

    # ---- Mocks ----
    mock_tcp_server = MagicMock()
    #mock_command_dispatcher = MagicMock()
    mock_tracker_center = MagicMock()
    mock_tracker_center.setup_mode = True

    # ---- Create instance ----
    handler = QueueHandler()
    handler.tcp_server = mock_tcp_server
    #handler.command_dispatcher = mock_command_dispatcher
    handler.tracker_center = mock_tracker_center

    # Inject test queues
    handler.response_queue_L = Queue()
    handler.response_queue_R = Queue()

    # Define test messages
    valid_dict_msg = {
        "category": "Data",
        "payload": {
            "focal_distance": 1.5,
            "coordinates": [100, 200],
            "detection_confidence": 0.9
        }
    }

    dict_missing_payload = {
        "category": "Data"
    }

    invalid_format_msg = "this is not a dict or bytes"

    png_msg = b'\x89PNG\r\n\x1a\n...'

    # Add test messages to left queue
    handler.response_queue_L.put(valid_dict_msg)
    handler.response_queue_L.put(dict_missing_payload)
    handler.response_queue_L.put(invalid_format_msg)
    handler.response_queue_L.put(png_msg)

    # Let handler process messages
    time.sleep(0.5)

    # ---- Assertions ----
    calls = mock_tcp_server.send.call_args_list
    print(f"[TEST] Total TCP send calls: {len(calls)}")
    assert len(calls) == 2, f"Expected 2 TCP sends, got {len(calls)}"

    def extract_message(call):
        if call[1] and "message" in call[1]:
            return call[1]["message"]
        elif call[0]:
            return call[0][0]  # Positional fallback
        return None

    json_calls = [extract_message(call) for call in calls if isinstance(extract_message(call), dict)]
    png_calls = [extract_message(call) for call in calls if isinstance(extract_message(call), bytes)]


    # Validate EyeloopData message
    assert len(json_calls) == 1, "Expected one JSON message"
    json_msg = json_calls[0]
    assert json_msg["type"] == "EyeloopData", "JSON message should be of type EyeloopData"
    assert "focal_distance" in json_msg["payload"], "Payload must contain focal_distance"

    # Validate PNG message
    assert len(png_calls) == 1, "Expected one PNG message"
    assert png_calls[0].startswith(b'\x89PNG'), "Expected PNG data to start with PNG header"

    print("[TEST PASSED] EyeloopQueueHandler correctly handled all message types.")



test_eyeloop_queue_handler()