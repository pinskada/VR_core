import os
import time
from vr_core.config import esp32_config
import vr_core.module_list as module_list
import threading


class ESP32:
    def __init__(self, force_mock=False):
        self.online = True

        module_list.esp32 = self  # Register the ESP32 in the module list
        self.health_monitor = module_list.health_monitor  # Reference to the health monitor

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
                self.health_monitor.failure("ESP32", f"pyserial not available {e}")
                print(f"[ERROR] ESP32: pyserial not available: {e}")
                self.online = False

        # Check for mock mode
        if self.mock_mode:
            self.online = True
            self.health_monitor.status("ESP32", "Mock mode active")
            print("[INFO] ESP32: MOCK MODE ACTIVE — Serial writes will be simulated.")
            return
        elif not os.path.exists(self.port): # Check if the serial port exists
            self.health_monitor.failure("ESP32", "Serial port not found")        
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
            print(f"[INFO] ESP32: Serial connection established on {self.port} @ {self.baudrate} baud.")
            self.thread = threading.Thread(target=self._perform_handshake, daemon=True)
            self.thread.start()  # Start the handshake thread

        except serial.SerialException as e:
            self.health_monitor.failure("ESP32", "Serial connection error")
            print(f"[ERROR] ESP32: Serial error: {e}.")
            self.online = False
            
    def is_online(self):
        return self.online

    def _perform_handshake(self):
        """Perform a handshake with the ESP32 to ensure it's ready."""

        while True:
            error = None

            for i in range(esp32_config.handshake_attempts):
                
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
                        print("[INFO] ESP32: andshake successful. ESP32 is ready.")
                        break
                    else:
                        print(f"[WARN] ESP32: Handshake failed. Expected: {esp32_config.handshake_response}, Received: {response}.")
                        error = f"Expected: {esp32_config.handshake_response}, Received: {response}"
                except Exception as e:
                    error = e
                    
                time.sleep(esp32_config.handshake_interval_inner)  # Wait before retrying the handshake

            if error != None:
                self.health_monitor.failure("ESP32", f"Handshake error: {error}")
                self.online = False
                print(f"[ERROR] ESP32: Handshake failed: {error}.")
                break

            time.sleep(esp32_config.handshake_interval_outer)  # Wait before retrying the handshake

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
        except Exception as e:
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
