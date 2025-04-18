import time
import argparse
from vr_core.config import gyroscope_config
from vr_core.raspberry_perif.gyroscope import Gyroscope

def test_gyroscope_basic_readings(force_mock=False):
    print("=== Starting Gyroscope Test ===")

    class DummySender:
        def send(self, message, priority='low'):
            print(f"[{priority.upper()}] {message}")

    gyro = Gyroscope(tcp_sender=DummySender(), force_mock=force_mock)

    if not gyro.online:
        print("[Gyroscope Test] Gyroscope failed to start.")
        return

    print(f"[Gyroscope Test] Mock Mode: {gyro.mock_mode}")
    print("Reading 50 gyro samples...\n")

    for i in range(50):
        data = gyro.read_gyro()
        print(f"[{i+1:03}] Simulated Gyro Data: {data}")
        time.sleep(gyroscope_config.update_rate)

    gyro.stop()
    print("=== Gyroscope Test Completed ===")



# --- Entry Point with CLI Args -----------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gyroscope Test")
    parser.add_argument("--mock", action="store_true", help="Force mock mode (no hardware)")
    args = parser.parse_args()

    test_gyroscope_basic_readings(force_mock=args.mock)
