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


test_case = 0

if test_case == 0:
    test_queue: Queue = Queue()

    esp = run_esp32_test(queue=test_queue, esp_mock_mode_s=False)

    for i in range(0, 10000, 5):
        test_queue.put(float(i))
        time.sleep(0.5)

    esp.stop()

elif test_case == 1:
    ser = serial.Serial('/dev/ttyAMA2', 115200, timeout=1)
    ser.reset_input_buffer()
    ser.write(b'PING\n')
    ser.flush()
    time.sleep(0.1)
    print("read:", ser.read(64))
    ser.close()
