# VR_core/tests/test_esp32.py

import argparse
from vr_core.raspberry_perif.esp32 import ESP32

def run_esp32_test(force_mock=False):
    print("\n=== [ESP32 TEST] Starting ===\n")
    
    # Instantiate the ESP32 class
    esp = ESP32(force_mock=force_mock)

    # Report status
    print(f"\n[RESULT] Mode: {'MOCK' if esp.mock_mode else 'REAL'}")
    print(f"[RESULT] Online: {esp.online}")

    if not esp.online:
        print("[TEST] ESP32 not available. Exiting.")
        print("\n=== [ESP32 TEST] Finished ===\n")
        print("[SUMMARY] ESP32 test FAILED — hardware not responsive.")
        return

    # Run test commands
    print("\n[TEST] Sending test focal distances...")
    for d in [30.0, 45.5, 60.0]:
        esp.send_focal_distance(d)

    esp.close()
    print("\n=== [ESP32 TEST] Finished ===\n")
    if esp.mock_mode:
        print("[SUMMARY] ESP32 test completed in MOCK MODE — no hardware verified.")
    elif esp.online:
        print("[SUMMARY] ESP32 test PASSED — device is connected and responding.")
    else:
        print("[SUMMARY] ESP32 test FAILED — hardware not responsive.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test ESP32 UART connection.")
    parser.add_argument('--mock', action='store_true', help="Force mock mode regardless of hardware availability.")
    args = parser.parse_args()

    run_esp32_test(force_mock=args.mock)
