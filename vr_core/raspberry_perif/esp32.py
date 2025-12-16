"""ESP32 Peripheral Module"""

import os
import queue
from typing import Optional, Any

try:
    import serial  # type: ignore  # pylint: disable=import-error
    from serial import Serial
except ImportError:  # ImportError on dev machines without pyserial
    serial = None  # type: ignore

from vr_core.config_service.config import Config
from vr_core.base_service import BaseService
from vr_core.utilities.logger_setup import setup_logger


class Esp32(BaseService):
    """ESP32 Peripheral Module."""
    def __init__(
        self,
        esp_cmd_q: queue.Queue,
        config: Config,
        esp_mock_mode_s: bool = False,
    ) -> None:
        super().__init__("ESP32")

        self.logger = setup_logger("ESP32")

        self.esp_cmd_q = esp_cmd_q

        self.cfg = config
        self._unsubscribe = config.subscribe(
            "ESP32",
            self._on_config_changed
        )

        self.esp_mock_mode_s = esp_mock_mode_s

        self.serial_conn: Optional[Serial] = None
        self.online = False

        #self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------
    def _on_start(self) -> None:
        """Initialize ESP32 serial connection."""

        if not self.esp_mock_mode_s:
            if not os.path.exists(self.cfg.esp32.port): # Check if the serial port exists
                self.logger.error("Serial port not found.")
                raise RuntimeError("ESP32 serial port not found")
            elif serial is None:
                self.logger.error("pyserial not installed. " \
                    "Run 'pip install pyserial' or enable mock mode.")
                raise RuntimeError("pyserial not installed")

            try:
                # Initialize the serial connection
                self.serial_conn = serial.Serial(
                    port=self.cfg.esp32.port,
                    baudrate=self.cfg.esp32.baudrate,
                    timeout=self.cfg.esp32.timeout
                )

                self._stop.wait(self.cfg.esp32.esp_boot_interval)  # Let ESP32 boot/reset

                if self._perform_handshake():
                    self.logger.info("Serial connection established on %s; %d.",
                        self.cfg.esp32.port, self.cfg.esp32.baudrate)
                    print("Handshake successful.")
                else:
                    self.logger.error("Failed to perform handshake with ESP32.")
                    raise RuntimeError("ESP32 handshake failed")

            except serial.SerialException as e:
                self.logger.error("Serial error: %s.", e)
                raise RuntimeError("ESP32 serial connection failed") from e

        # Check for mock mode
        else:
            self.logger.info("Running in mock mode; skipping serial connection.")

        self.online = True

        self._ready.set()
        #self.logger.info("Service is ready.")

    def _run(self) -> None:
        """Main service loop."""
        while not self._stop.is_set():
            self._cmd_queue()


    def _on_stop(self) -> None:
        """Cleanup resources."""
        #self.logger.info("Stopping service.")
        self.online = False

        if self.serial_conn and hasattr(self.serial_conn, "is_open") and self.serial_conn.is_open:
            self.serial_conn.close()
        else:
            self.logger.warning("Serial connection already closed or was never opened.")

        self._unsubscribe()


# ---------- Internals ----------

    def _perform_handshake(self) -> bool:
        """Perform a handshake with the ESP32 to ensure it's ready."""

        if not self.serial_conn:
            self.logger.error("Serial connection not initialized.")
            return False

        for _ in range(self.cfg.esp32.handshake_attempts):

            try:

                # Send the handshake message in a byte format
                self.serial_conn.write((self.cfg.esp32.handshake_message + "\n").encode("utf-8"))

                # Wait for a response from the ESP32
                response = self.serial_conn.readline().decode("utf-8").strip()

                # Check if the response matches the expected response
                if response == self.cfg.esp32.handshake_response:
                    return True
                else:
                    self.logger.warning("Handshake failed. Expected:"
                        " %s, Received: %s",
                        self.cfg.esp32.handshake_response, response
                    )
            except (OSError, UnicodeDecodeError) as e:
                # Catch specific errors that can occur during serial I/O and decoding
                self.logger.warning("Handshake error: %s.", e)
            # Wait before retrying the handshake
            self._stop.wait(self.cfg.esp32.handshake_interval)

        return False


    def _cmd_queue(self) -> None:
        """Process commands from the command queue."""

        try:
            message = self.esp_cmd_q.get(timeout=self.cfg.esp32.cmd_queue_timeout)
            if isinstance(message, float):
                #self.logger.info(f"Sent gaze distance: {message}")
                self._send_gaze_distance(message)
            else:
                self.logger.warning("Unknown command received in ESP32 queue: %s", message)
        except queue.Empty:
            return


    def _send_gaze_distance(self, distance_m: float):
        """Send the gaze distance to the ESP32."""

        distance_mm = distance_m * 1000

        # Parse the message to send
        message = f'f"{distance_mm:.2f}\n'

        # Fake the message for mock mode
        if self.esp_mock_mode_s:
            # self.logger.info("Would send gaze distance: %s", message.strip())
            return

        try:
            if not self.serial_conn:
                self.logger.error("Serial connection not initialized.")
                return
            self.serial_conn.write(message.encode('utf-8'))
            self.logger.info("Sent gaze distance: %s", message.strip())
        except (OSError, AttributeError) as e:
            # OSError covers low-level I/O errors from the serial port,
            # AttributeError covers cases where serial_conn is None or missing methods.
            self.logger.warning("Error during UART write: %s", e)


    #  pylint: disable=unused-argument
    def _on_config_changed(self, path: str, old_val: Any, new_val: Any) -> None:
        """Handle configuration changes."""
