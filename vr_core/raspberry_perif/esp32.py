"""ESP32 Peripheral Module"""

import os
import time
import threading

from vr_core.config import esp32_config
import vr_core.module_list as module_list


class ESP32:
    """ESP32 Peripheral Module."""
    def __init__(self, force_mock=False):
        self.online = True

        module_list.esp32 = self  # Register the ESP32 in the module list

        # Import the ESP32 configuration
        self.port = esp32_config.port
        self.baudrate = esp32_config.baudrate
        self.timeout = esp32_config.timeout
        self.mock_mode = force_mock
        self.serial_conn = None

        if not self.mock_mode:
            try:
                import serial # type: ignore
            except ImportError as e:
                if module_list.health_monitor:
                    module_list.health_monitor.failure("ESP32", f"pyserial not available {e}")
                else:
                    print("[WARN] ESP32: No HealthMonitor available for failure updates.")
                print(f"[ERROR] ESP32: pyserial not available: {e}")
                self.online = False

        # Check for mock mode
        if self.mock_mode:
            self.online = True
            if module_list.health_monitor:
                module_list.health_monitor.status("ESP32", "Mock mode active")
            else:
                print("[WARN] ESP32: No HealthMonitor available for failure updates.")
            print("[INFO] ESP32: MOCK MODE ACTIVE — Serial writes will be simulated.")
            return
        elif not os.path.exists(self.port): # Check if the serial port exists
            if module_list.health_monitor:
                module_list.health_monitor.failure("ESP32", "Serial port not found")
            else:
                print("[WARN] ESP32: No HealthMonitor available for failure updates.")
            print("[ERROR] ESP32: Serial port not found.")
            self.online = False
            return

        try:
            # Initialize the serial connection
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )

            time.sleep(2)  # Let ESP32 boot/reset
            print(f"[INFO] ESP32: Serial connection established on {self.port}; {self.baudrate}.")
            self.thread = threading.Thread(target=self._perform_handshake, daemon=True)
            self.thread.start()  # Start the handshake thread

        except serial.SerialException as e:
            if module_list.health_monitor:
                module_list.health_monitor.failure("ESP32", "Serial connection error")
            else:
                print("[WARN] ESP32: No HealthMonitor available for failure updates.")
            print(f"[ERROR] ESP32: Serial error: {e}.")
            self.online = False

    def is_online(self):
        """Check if the ESP32 is online."""
        return self.online

    def _perform_handshake(self):
        """Perform a handshake with the ESP32 to ensure it's ready."""

        while True:
            error = None

            for _ in range(esp32_config.handshake_attempts):

                try:
                    # Send the handshake message in a byte format
                    self.serial_conn.write((esp32_config.handshake_message + "\n").encode("utf-8"))
                    print(f"[INFO] ESP32: Sent handshake: {esp32_config.handshake_message}")

                    # Wait for a response from the ESP32
                    response = self.serial_conn.readline().decode("utf-8").strip()
                    print(f"[INFO] ESP32: Handshake response: {response}")

                    # Check if the response matches the expected response
                    if response == esp32_config.handshake_response:
                        self.online = True
                        error = None
                        print("[INFO] ESP32: Handshake successful. ESP32 is ready.")
                        break
                    else:
                        print("[WARN] ESP32: Handshake failed. Expected:"
                            f" {esp32_config.handshake_response}, Received: {response}."
                        )
                        error = f"Expected: {esp32_config.handshake_response}, Received: {response}"
                except (OSError, UnicodeDecodeError) as e:
                    # Catch specific errors that can occur during serial I/O and decoding
                    error = e
                # Wait before retrying the handshake
                time.sleep(esp32_config.handshake_interval_inner)

            if error is not None:
                if module_list.health_monitor:
                    module_list.health_monitor.failure("ESP32", f"Handshake error: {error}")
                else:
                    print("[WARN] ESP32: No HealthMonitor available for failure updates.")
                self.online = False
                print(f"[ERROR] ESP32: Handshake failed: {error}.")
                break

            # Handshake successful; report and stop retrying
            if module_list.health_monitor:
                module_list.health_monitor.status("ESP32", "Handshake successful")
            else:
                print("[WARN] ESP32: No HealthMonitor available for failure updates.")
            print("[INFO] ESP32: Handshake completed successfully.")
            break

    def send_gaze_distance(self, distance_mm: float):
        """Send the gaze distance to the ESP32."""

        # Create the message to send
        message = f"{distance_mm:.2f}\n"

        # Fake the message for mock mode
        if self.mock_mode:
            print(f"[INFO] ESP32: Would send gaze distance: {message.strip()}")
            return

        try:
            self.serial_conn.write(message.encode('utf-8'))
            print(f"[INFO] ESP32: Sent gaze distance: {message.strip()}")
        except (OSError, AttributeError) as e:
            # OSError covers low-level I/O errors from the serial port,
            # AttributeError covers cases where serial_conn is None or missing methods.
            print(f"[WARN] ESP32: Error during UART write: {e}")

    def close(self):
        """Close the serial connection."""

        if self.mock_mode:
            print("[INFO] ESP32: Mock mode — no connection to close.")
            return

        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            self.online = False
            print("[INFO] ESP32: Serial connection closed.")
