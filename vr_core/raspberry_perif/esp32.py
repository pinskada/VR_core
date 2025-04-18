import os
import time
from vr_core.config import esp32_config

try:
    import serial # type: ignore
    HARDWARE_AVAILABLE = True
except ImportError:
    print("[ESP32] pyserial not available — mock mode")
    HARDWARE_AVAILABLE = False


class ESP32:
    def __init__(self, force_mock=False):

        # Import the ESP32 configuration
        self.port = esp32_config.port
        self.baudrate = esp32_config.baudrate
        self.timeout = esp32_config.timeout
        self.mock_mode = force_mock
        self.serial_conn = None
        self.online = False

        # Check for mock mode
        if self.mock_mode:
            self.online = True
            print("[ESP32] MOCK MODE ACTIVE — Serial writes will be simulated.")
            return
        elif not os.path.exists(self.port): # Check if the serial port exists          
            print("[ESP32] Serial port not found.")
            return

        try:
            # Initialize the serial connection
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )

            time.sleep(2)  # Let ESP32 boot/reset
            print(f"[ESP32] Serial connection established on {self.port} @ {self.baudrate} baud.")
            self._perform_handshake() # Perform handshake with ESP32

        except serial.SerialException as e:            
            print(f"[ESP32] Serial error: {e}.")


    def is_online(self):
        return self.online
    

    def _perform_handshake(self):
        """Perform a handshake with the ESP32 to ensure it's ready."""

        for i in range(esp32_config.handshake_attempts):
            print(f"[ESP32] Handshake attempt {i + 1}/{esp32_config.handshake_attempts}")

            try:
                # Send the handshake message in a byte format
                self.serial_conn.write((esp32_config.handshake_message + "\n").encode("utf-8"))
                print(f"[ESP32] Sent handshake: {esp32_config.handshake_message}")

                # Wait for a response from the ESP32
                response = self.serial_conn.readline().decode("utf-8").strip()
                print(f"[ESP32] Handshake response: {response}")

                # Check if the response matches the expected response
                if response != esp32_config.handshake_response: 
                    print(f"[ESP32] Handshake failed. Expected: {esp32_config.handshake_response}, Received: {response}.")
                else:
                    self.online = True
                    print("[ESP32] Handshake successful. ESP32 is ready.")
                    return
                
            except Exception as e:
                print(f"[ESP32] Handshake failed: {e}.")
            

    def send_focal_distance(self, distance_mm: float):
        """Send the focal distance to the ESP32."""

        # Create the message to send
        message = f"{distance_mm:.2f}\n"

        # Fake the message for mock mode
        if self.mock_mode:
            print(f"[ESP32][MOCK] Would send focal distance: {message.strip()}")
            return

        for i in range(esp32_config.send_attempts):  # Retry sending the message 3 times
            try:
                self.serial_conn.write(message.encode('utf-8'))
                print(f"[ESP32] Sent focal distance: {message.strip()}")
            except Exception as e:
                if i == esp32_config.send_attempts-1:
                    self.online = False
                print(f"[ESP32] Error during UART write: {e}")


    def close(self):
        """Close the serial connection."""

        if self.mock_mode:
            print("[ESP32] Mock mode — no connection to close.")
            return

        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            self.online = False
            print("[ESP32] Serial connection closed.")
