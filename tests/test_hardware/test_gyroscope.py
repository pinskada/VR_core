# File: tests/test_gyroscope.py

import time
from vr_core.raspberry_perif.gyroscope import Gyroscope
from vr_core.config import gyroscope_config

def test_gyroscope_basic_readings():
    print("=== Starting Gyroscope Test ===")

    class DummySender:
        def send(self, message, priority='low'):
            print(f"[{priority.upper()}] {message}")

    try:
        gyro = Gyroscope(tcp_sender=DummySender())
        print(f"Mock Mode: {gyro.mock_mode}\n")

        for i in range(50):
            data = gyro.read_gyro()
            print(f"[{i+1:03}] Simulated Gyro Data: {data}")
            time.sleep(gyroscope_config.update_rate)

        gyro.stop()
        print("=== Gyroscope Test Completed ===")

    except KeyboardInterrupt:
        print("Test interrupted.")
    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    test_gyroscope_basic_readings()