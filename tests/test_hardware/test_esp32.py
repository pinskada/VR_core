"""Test module for ESP32."""

from queue import Queue
from threading import Event
import time

import serial

from vr_core.raspberry_perif.esp32 import Esp32
from vr_core.config_service.config import Config


def run_esp32_test(queue: Queue, esp_mock_mode_s=False) -> Esp32:
    """Test rpi <-> esp connection"""
    print("\n=== [ESP32 TEST] Starting ===\n")

    config_ready_s = Event()

    config = Config(
        config_ready_s=config_ready_s,
        mock_mode=True,
    )

    # Instantiate the ESP32 class
    esp = Esp32(
        esp_cmd_q=queue,
        config=config,
        esp_mock_mode_s=esp_mock_mode_s,
    )
    config.start()
    esp.start()

    return esp

test_queue: Queue = Queue()

esp = run_esp32_test(queue=test_queue, esp_mock_mode_s=False)

# for i in range(0, 10000, 500):
#     test_queue.put(float(i))
#     time.sleep(0.2)

# print("Test ended.")

esp.stop()

# ser = serial.Serial('/dev/ttyAMA0', 115200, timeout=0.5)
# ser.reset_input_buffer()
# ser.reset_output_buffer()
# time.sleep(0.1)
# ser.write(b'PING\n')
# time.sleep(0.1)
# print("got:", ser.readline())
# ser.close()
